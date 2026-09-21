"""glsim — a small GenVM stand-in, good enough to execute the real contracts.

This is not a test. It is the harness the tests run on. It exists so the
DETERMINISTIC HALF of each contract can be executed for real: storage writes,
the post-consensus re-derivation, every refusal path, and every branch that
only fires when the leader and a validator saw different things.

It deliberately models the parts of GenVM that cause bugs, and it models them
at the earliest possible moment. Everything in section 8 of the specification
that can be detected mechanically is detected here, at class definition time or
at the block boundary, so a mistake that would cost a failed deployment costs a
failed test instead.

What it refuses, and when:

  class definition   a collection inside a storage dataclass
                     int / list / dict / tuple as a storage field type
                     a bare, unsubscripted DynArray or TreeMap
  memory allocation  gl.storage.inmem_allocate() handed a collection
  block boundary     a return value that is not a flat dict of str
  block body         any read of a live storage object

The block boundary check is the important one. On chain, a nested mapping or a
bool in a block's return value fails inside the calldata encoder, which runs
OUTSIDE the contract: the transaction comes back with Result Code <unknown>,
no stderr and no traceback at all. Nothing in the contract can catch it and
nothing tells you where to look. Here it is a loud, immediate TypeError.

The other property that matters: a block runs TWICE, once as the leader and
once as a validator, and the two can be given completely independent mock
answers. Every mocking framework feeds both nodes the same data by default,
which is exactly why a contract that quietly assumes both nodes see identical
bytes passes its suite and then fails on a real network.
"""

import copy
import sys
import types


# ---------------------------------------------------------------------------
# storage types
# ---------------------------------------------------------------------------

class _Generic:
    """What DynArray[T] and TreeMap[K, V] evaluate to.

    Deliberately NOT callable. Real GenVM refuses `DynArray[T]()` with
    "this class can't be instantiated by user", because storage generics have a
    fixed memory layout and no type erasure. The only legal way to obtain one is
    to declare it as a top level contract field and let the runtime allocate it.
    """

    def __init__(self, origin, params=None):
        self.__origin__ = origin
        self.__args__ = params

    def __call__(self, *a, **kw):
        raise TypeError("this class can't be instantiated by user")

    def __repr__(self):
        return "%s[...]" % self.__origin__.__name__


class DynArray(list):
    def __class_getitem__(cls, item):
        return _Generic(DynArray, item)

    def truncate(self):
        self.clear()


class TreeMap(dict):
    def __class_getitem__(cls, item):
        return _Generic(TreeMap, item)


class Address(str):
    @staticmethod
    def zero():
        return Address("0x" + "0" * 40)


def u256(v=0):
    return int(v)


def u8(v=0):
    return int(v)


def i256(v=0):
    return int(v)


_FORBIDDEN_STORAGE = {
    int: "int (use u256, i256 or bigint)",
    list: "list (use DynArray[T])",
    dict: "dict (use TreeMap[K, V])",
    tuple: "tuple",
    set: "set",
}


def _reject_bad_storage_annotation(owner, name, ann):
    """The three storage rules that can be checked from an annotation alone."""
    origin = getattr(ann, "__origin__", None)

    if ann in _FORBIDDEN_STORAGE:
        raise TypeError(
            "%s.%s: %s is not a valid storage type"
            % (owner, name, _FORBIDDEN_STORAGE[ann])
        )
    if origin in (list, dict, tuple, set):
        raise TypeError(
            "%s.%s: builtin containers are not valid storage types, "
            "use DynArray[T] or TreeMap[K, V]" % (owner, name)
        )
    if ann is DynArray or ann is TreeMap:
        raise TypeError(
            "%s.%s: only fully instantiated generics are allowed. Write "
            "DynArray[T] or TreeMap[K, V], never the bare name." % (owner, name)
        )


def allow_storage(cls):
    """Marks a dataclass as storable, and refuses what GenVM refuses.

    A storage dataclass cannot contain a collection. On chain the first write
    fails with "this class can't be instantiated by user", deep inside the
    runner, and gl.storage.inmem_allocate does not rescue it. Catching it at
    class definition time turns a failed deployment into a failed import.
    """
    for name, ann in getattr(cls, "__annotations__", {}).items():
        origin = getattr(ann, "__origin__", None)
        if ann in (DynArray, TreeMap) or origin in (DynArray, TreeMap):
            raise TypeError(
                "%s.%s: a storage dataclass cannot contain a collection. Make it "
                "a top level contract field and carry a parent id on the record "
                "instead." % (cls.__name__, name)
            )
        _reject_bad_storage_annotation(cls.__name__, name, ann)
    return cls


# ---------------------------------------------------------------------------
# errors and results
# ---------------------------------------------------------------------------

class UserError(Exception):
    def __init__(self, message=""):
        super().__init__(message)
        self.message = message


class VMError(Exception):
    pass


class Result:
    pass


class Return(Result):
    def __init__(self, calldata):
        self.calldata = calldata


class Rollback(Result):
    def __init__(self, message):
        self.message = message


class ContractError(Result):
    def __init__(self, message):
        self.message = message


class StorageInNondet(Exception):
    """Raised when a block touches a live storage object.

    On chain a non-deterministic block cannot read storage at all. Contracts
    must extract plain values first, or use gl.storage.copy_to_memory().
    """


# ---------------------------------------------------------------------------
# the block boundary
# ---------------------------------------------------------------------------

def check_calldata_shape(value, where="leader_fn"):
    """A block's return value must be a FLAT dict of str. Nothing else.

    This mirrors the calldata encoder, which runs outside the contract. When it
    fails on chain there is no traceback, no stderr, and the result code is
    <unknown>; the only signal is that the transaction did not work. Modelling
    it as a plain TypeError here is the difference between a five minute fix and
    an evening.
    """
    if not isinstance(value, dict):
        raise TypeError(
            "%s returned %s. A block's return value must be a flat dict of str; "
            "on chain anything else fails inside the calldata encoder with "
            "Result Code <unknown> and no traceback."
            % (where, type(value).__name__)
        )
    for k, v in value.items():
        if not isinstance(k, str):
            raise TypeError(
                "%s returned a key of type %s. Keys must be str."
                % (where, type(k).__name__)
            )
        if isinstance(v, bool):
            raise TypeError(
                "%s returned a bool for %r. A bool does not survive the calldata "
                "encoder; send \"yes\" / \"no\" as str." % (where, k)
            )
        if not isinstance(v, str):
            raise TypeError(
                "%s returned %s for %r. Every value must be str: no nested "
                "mapping, no list, no number." % (where, type(v).__name__, k)
            )
    return value


# ---------------------------------------------------------------------------
# the non-deterministic environment
# ---------------------------------------------------------------------------

class NonDetEnv:
    """The mock answers for ONE node. The leader and validator get their own."""

    def __init__(self, prompts=None, pages=None):
        self.prompts = prompts or {}
        self.pages = pages or {}
        self.prompt_calls = []
        self.render_calls = []

    def exec_prompt(self, prompt, response_format=None, images=None):
        self.prompt_calls.append(prompt)
        for key, value in self.prompts.items():
            if key in prompt:
                if isinstance(value, Exception):
                    raise value
                return copy.deepcopy(value)
        raise UserError("no mock prompt response matched")

    def render(self, url, mode="text"):
        self.render_calls.append((url, mode))
        for key, value in self.pages.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise UserError("no mock page for %s" % url)


class _Runtime:
    def __init__(self):
        self.leader_env = NonDetEnv()
        self.validator_env = NonDetEnv()
        self.active = None
        self.sender = Address("0x" + "11" * 20)
        self.origin = None
        self.value = 0
        self.datetime = "2026-08-24T10:00:00Z"
        self.last_validator_verdict = None
        self.block_runs = 0


RT = _Runtime()


def _run_nondet_unsafe(leader_fn, validator_fn):
    """Run the block as the leader, then as a validator, then decide.

    The leader's return value is shape-checked exactly where the real encoder
    would run: after the block returns and before anything else can see it.
    """
    RT.block_runs += 1

    RT.active = RT.leader_env
    try:
        leader_out = leader_fn()
        check_calldata_shape(leader_out, "leader_fn")
        leaders_res = Return(leader_out)
    except UserError as e:
        leaders_res, leader_out = Rollback(e.message), None
    except TypeError:
        RT.active = None
        raise
    except Exception as e:                                    # noqa: BLE001
        leaders_res, leader_out = ContractError(str(e)), None

    RT.active = RT.validator_env
    try:
        verdict = bool(validator_fn(leaders_res))
    finally:
        RT.active = None
    RT.last_validator_verdict = verdict

    if not verdict:
        raise UserError("validators did not agree with the leader")
    if not isinstance(leaders_res, Return):
        raise UserError("leader failed")
    return leader_out


# ---------------------------------------------------------------------------
# the gl namespace
# ---------------------------------------------------------------------------

def _identity(fn):
    return fn


class _Write:
    def __call__(self, fn):
        return fn

    @property
    def payable(self):
        return _identity


class _Public:
    def __init__(self):
        self.view = _identity
        self.write = _Write()


class _Message:
    @property
    def sender_address(self):
        return RT.sender

    @property
    def origin_address(self):
        return RT.origin or RT.sender

    @property
    def value(self):
        return RT.value


class _Web:
    def render(self, url, mode="text"):
        if RT.active is None:
            raise VMError("web access outside a non-deterministic block")
        return RT.active.render(url, mode)


class _NonDet:
    def __init__(self):
        self.web = _Web()

    def exec_prompt(self, prompt, response_format=None, images=None):
        if RT.active is None:
            raise VMError("prompt outside a non-deterministic block")
        return RT.active.exec_prompt(prompt, response_format, images)


class _VM:
    UserError = UserError
    VMError = VMError
    Result = Result
    Return = Return
    Rollback = Rollback
    ContractError = ContractError
    run_nondet_unsafe = staticmethod(_run_nondet_unsafe)
    run_nondet = staticmethod(_run_nondet_unsafe)


class _EqPrinciple:
    @staticmethod
    def strict_eq(fn):
        def validator(leaders_res):
            if not isinstance(leaders_res, Return):
                return False
            return fn() == leaders_res.calldata
        return _run_nondet_unsafe(fn, validator)


class _Contract:
    """Base class. Storage fields are created from the class annotations."""

    def __new__(cls, *a, **kw):
        obj = super().__new__(cls)
        anns = getattr(cls, "__annotations__", {})
        for name, ann in anns.items():
            _reject_bad_storage_annotation(cls.__name__, name, ann)
        for name, ann in anns.items():
            origin = getattr(ann, "__origin__", None)
            if origin is DynArray:
                setattr(obj, name, DynArray())
            elif origin is TreeMap:
                setattr(obj, name, TreeMap())
            elif ann is str:
                setattr(obj, name, "")
            elif ann is bool:
                setattr(obj, name, False)
            elif ann is Address:
                setattr(obj, name, Address.zero())
            elif origin is not None:
                setattr(obj, name, origin())
            else:
                setattr(obj, name, None)
        return obj


class _Storage:
    @staticmethod
    def copy_to_memory(x):
        return copy.deepcopy(x)

    @staticmethod
    def inmem_allocate(t, *a, **kw):
        """Mirrors gl.storage.inmem_allocate, including what it CANNOT do.

        The real function takes a fully instantiated GENERIC DATACLASS and the
        arguments its __init__ would take. It is not a way to build a
        collection: handing it DynArray[T] fails on chain with
        "_GenericAlias.__init__() missing 1 required positional argument".
        """
        origin = getattr(t, "__origin__", t)
        if origin in (DynArray, TreeMap):
            raise TypeError(
                "inmem_allocate cannot build a storage collection. Declare it as "
                "a top level contract field instead; the runtime allocates those."
            )
        return origin(*a, **kw)


class _GL:
    def __init__(self):
        self.Contract = _Contract
        self.public = _Public()
        self.message = _Message()
        self.nondet = _NonDet()
        self.vm = _VM()
        self.eq_principle = _EqPrinciple()
        self.storage = _Storage()
        self.message_raw = {"datetime": RT.datetime, "is_init": True, "stack": []}


gl = _GL()


# ---------------------------------------------------------------------------
# loading a real contract file
# ---------------------------------------------------------------------------

def _install_module():
    from dataclasses import dataclass as _dc
    m = types.ModuleType("genlayer")
    m.gl = gl
    m.DynArray = DynArray
    m.TreeMap = TreeMap
    m.Address = Address
    m.u256 = u256
    m.u8 = u8
    m.i256 = i256
    m.allow_storage = allow_storage
    m.dataclass = _dc
    m.__all__ = [
        "gl", "DynArray", "TreeMap", "Address", "u256", "u8", "i256",
        "allow_storage", "dataclass",
    ]
    sys.modules["genlayer"] = m


_install_module()


def load_contract(path):
    """Execute a real contract file and return its namespace."""
    src = open(path, encoding="utf-8").read()
    ns = {"__name__": "contract_%s" % path.replace("\\", "_").replace("/", "_")}
    exec(compile(src, path, "exec"), ns)
    return types.SimpleNamespace(**ns)


def deploy(path, *args):
    """Instantiate the contract, exactly as GenVM would."""
    mod = load_contract(path)
    gl.message_raw["is_init"] = True
    c = mod.Contract(*args)
    gl.message_raw["is_init"] = False
    c._module = mod
    return c


def set_mocks(prompts=None, v_prompts=None, pages=None, v_pages=None):
    """Give the leader and the validator their own view of the world.

    Passing only `prompts` makes both nodes see the same answers, which is the
    common case. Passing `v_prompts` is how divergence is tested, and it is the
    single most useful thing this harness does.
    """
    RT.leader_env = NonDetEnv(prompts, pages)
    RT.validator_env = NonDetEnv(
        v_prompts if v_prompts is not None else prompts,
        v_pages if v_pages is not None else pages,
    )
    RT.block_runs = 0
    RT.last_validator_verdict = None


def set_sender(addr):
    RT.sender = Address(addr)


def set_time(iso):
    RT.datetime = iso
    gl.message_raw["datetime"] = iso


def call(contract, method, *args):
    """Call a method with storage rollback on failure, as the runtime does."""
    snapshot = {
        k: copy.deepcopy(v)
        for k, v in contract.__dict__.items()
        if not k.startswith("_")
    }
    try:
        return getattr(contract, method)(*args)
    except Exception:
        for k, v in snapshot.items():
            setattr(contract, k, v)
        raise
