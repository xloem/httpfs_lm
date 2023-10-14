import functools
import trace

import torch
import io
import os
import pickle
from typing import Any, BinaryIO, Callable, cast, Dict, Optional, Type, Tuple, Union, IO
from torch.serialization import (
    FILE_LIKE, MAP_LOCATION,
    _check_dill_version, _get_restore_location,
    _is_zipfile, _is_torchscript_zip, _maybe_decode_ascii, 
    _open_file_like, _open_zipfile_reader,
    StorageType,
)

# presently patched from torch.serialization 2.0.1

# returns meta tensors where tensor.remote_fetch() makes a real one that actually reads the data
# and tensor.remote_name contains the data filename in the zip
# note: you might be able to pass an http remote fileobject to load(), but i've only tried/troubleshooted local filepaths

def load(
    f: FILE_LIKE,
    map_location: MAP_LOCATION = None,
    pickle_module: Any = None,
    *,
    weights_only: bool = False,
    **pickle_load_args: Any
) -> Any:
    # Reference: https://github.com/pytorch/pytorch/issues/54354
    # The first line of this docstring overrides the one Sphinx generates for the
    # documentation. We need it so that Sphinx doesn't leak `pickle`s path from
    # the build environment (e.g. `<module 'pickle' from '/leaked/path').

    """load(f, map_location=None, pickle_module=pickle, *, weights_only=False, **pickle_load_args)

    Loads an object saved with :func:`torch.save` from a file.

    :func:`torch.load` uses Python's unpickling facilities but treats storages,
    which underlie tensors, specially. They are first deserialized on the
    CPU and are then moved to the device they were saved from. If this fails
    (e.g. because the run time system doesn't have certain devices), an exception
    is raised. However, storages can be dynamically remapped to an alternative
    set of devices using the :attr:`map_location` argument.

    If :attr:`map_location` is a callable, it will be called once for each serialized
    storage with two arguments: storage and location. The storage argument
    will be the initial deserialization of the storage, residing on the CPU.
    Each serialized storage has a location tag associated with it which
    identifies the device it was saved from, and this tag is the second
    argument passed to :attr:`map_location`. The builtin location tags are ``'cpu'``
    for CPU tensors and ``'cuda:device_id'`` (e.g. ``'cuda:2'``) for CUDA tensors.
    :attr:`map_location` should return either ``None`` or a storage. If
    :attr:`map_location` returns a storage, it will be used as the final deserialized
    object, already moved to the right device. Otherwise, :func:`torch.load` will
    fall back to the default behavior, as if :attr:`map_location` wasn't specified.

    If :attr:`map_location` is a :class:`torch.device` object or a string containing
    a device tag, it indicates the location where all tensors should be loaded.

    Otherwise, if :attr:`map_location` is a dict, it will be used to remap location tags
    appearing in the file (keys), to ones that specify where to put the
    storages (values).

    User extensions can register their own location tags and tagging and
    deserialization methods using :func:`torch.serialization.register_package`.

    Args:
        f: a file-like object (has to implement :meth:`read`, :meth:`readline`, :meth:`tell`, and :meth:`seek`),
            or a string or os.PathLike object containing a file name
        map_location: a function, :class:`torch.device`, string or a dict specifying how to remap storage
            locations
        pickle_module: module used for unpickling metadata and objects (has to
            match the :attr:`pickle_module` used to serialize file)
        weights_only: Indicates whether unpickler should be restricted to
            loading only tensors, primitive types and dictionaries
        pickle_load_args: (Python 3 only) optional keyword arguments passed over to
            :func:`pickle_module.load` and :func:`pickle_module.Unpickler`, e.g.,
            :attr:`errors=...`.

    .. warning::
        :func:`torch.load()` unless `weights_only` parameter is set to `True`,
        uses ``pickle`` module implicitly, which is known to be insecure.
        It is possible to construct malicious pickle data which will execute arbitrary code
        during unpickling. Never load data that could have come from an untrusted
        source in an unsafe mode, or that could have been tampered with. **Only load data you trust**.

    .. note::
        When you call :func:`torch.load()` on a file which contains GPU tensors, those tensors
        will be loaded to GPU by default. You can call ``torch.load(.., map_location='cpu')``
        and then :meth:`load_state_dict` to avoid GPU RAM surge when loading a model checkpoint.

    .. note::
        By default, we decode byte strings as ``utf-8``.  This is to avoid a common error
        case ``UnicodeDecodeError: 'ascii' codec can't decode byte 0x...``
        when loading files saved by Python 2 in Python 3.  If this default
        is incorrect, you may use an extra :attr:`encoding` keyword argument to specify how
        these objects should be loaded, e.g., :attr:`encoding='latin1'` decodes them
        to strings using ``latin1`` encoding, and :attr:`encoding='bytes'` keeps them
        as byte arrays which can be decoded later with ``byte_array.decode(...)``.

    Example:
        >>> # xdoctest: +SKIP("undefined filepaths")
        >>> torch.load('tensors.pt')
        # Load all tensors onto the CPU
        >>> torch.load('tensors.pt', map_location=torch.device('cpu'))
        # Load all tensors onto the CPU, using a function
        >>> torch.load('tensors.pt', map_location=lambda storage, loc: storage)
        # Load all tensors onto GPU 1
        >>> torch.load('tensors.pt', map_location=lambda storage, loc: storage.cuda(1))
        # Map tensors from GPU 1 to GPU 0
        >>> torch.load('tensors.pt', map_location={'cuda:1': 'cuda:0'})
        # Load tensor from io.BytesIO object
        >>> with open('tensor.pt', 'rb') as f:
        ...     buffer = io.BytesIO(f.read())
        >>> torch.load(buffer)
        # Load a module with 'ascii' encoding for unpickling
        >>> torch.load('module.pt', encoding='ascii')
    """
    torch._C._log_api_usage_once("torch.load")
    UNSAFE_MESSAGE = (
        "Weights only load failed. Re-running `torch.load` with `weights_only` set to `False`"
        " will likely succeed, but it can result in arbitrary code execution."
        "Do it only if you get the file from a trusted source. WeightsUnpickler error: "
    )
    # Add ability to force safe only weight loads via environment variable
    if os.getenv("TORCH_FORCE_WEIGHTS_ONLY_LOAD", "0").lower() in ['1', 'y', 'yes', 'true']:
        weights_only = True

    if weights_only:
        if pickle_module is not None:
            raise RuntimeError("Can not safely load weights when explicit pickle_module is specified")
    else:
        if pickle_module is None:
            pickle_module = pickle

    _check_dill_version(pickle_module)

    if 'encoding' not in pickle_load_args.keys():
        pickle_load_args['encoding'] = 'utf-8'

    if True:
        opened_file = _open_file_like(f, 'rb').__enter__()
        if _is_zipfile(opened_file):
            # The zipfile reader is going to advance the current file position.
            # If we want to actually tail call to torch.jit.load, we need to
            # reset back to the original position.
            orig_position = opened_file.tell()
            if True:
                opened_zipfile = _open_zipfile_reader(opened_file).__enter__()
                if _is_torchscript_zip(opened_zipfile):
                    warnings.warn("'torch.load' received a zip file that looks like a TorchScript archive"
                                  " dispatching to 'torch.jit.load' (call 'torch.jit.load' directly to"
                                  " silence this warning)", UserWarning)
                    opened_file.seek(orig_position)
                    return torch.jit.load(opened_file, map_location=map_location)
                if weights_only:
                    try:
                        return _load(opened_zipfile, map_location, _weights_only_unpickler, **pickle_load_args)
                    except RuntimeError as e:
                        raise pickle.UnpicklingError(UNSAFE_MESSAGE + str(e)) from None
                return _load(opened_zipfile, map_location, pickle_module, **pickle_load_args)
        if weights_only:
            try:
                return _legacy_load(opened_file, map_location, _weights_only_unpickler, **pickle_load_args)
            except RuntimeError as e:
                raise pickle.UnpicklingError(UNSAFE_MESSAGE + str(e)) from None
        return _legacy_load(opened_file, map_location, pickle_module, **pickle_load_args)

def _load(zip_file, map_location, pickle_module, pickle_file='data.pkl', **pickle_load_args):
    restore_location = _get_restore_location(map_location)

    #loaded_storages = {}

    def load_tensor(dtype, numel, key, location):
        name = f'data/{key}'

        storage = zip_file.get_storage_from_record(name, numel, torch.UntypedStorage)._typed_storage()._untyped_storage
        # TODO: Once we decide to break serialization FC, we can
        # stop wrapping with TypedStorage
        typed_storage = torch.storage.TypedStorage(
            wrap_storage=restore_location(storage, location),
            dtype=dtype,
            _internal=True)

        #if typed_storage._data_ptr() != 0:
        #    loaded_storages[key] = typed_storage

        return typed_storage

    def makeRemoteTensor(Constructor):
        def RemoteTensor(data, *params, **kwparams):
            typename, storage_type, key, location, numel, dtype, nbytes = data
            tensor = Constructor(torch.TypedStorage(numel, dtype=dtype, device='meta', _internal=True), *params, **kwparams)
            def fetch():
                typed_storage = load_tensor(dtype, nbytes, key, _maybe_decode_ascii(location))
                return Constructor(typed_storage, *params, **kwparams)
            tensor.remote_fetch = fetch
            tensor.remote_name = f'data/{key}'
            return tensor
        return RemoteTensor

    def persistent_load(saved_id):
        assert isinstance(saved_id, tuple)
        typename = _maybe_decode_ascii(saved_id[0])
        data = saved_id[1:]

        assert typename == 'storage', \
            f"Unknown typename for persistent_load, expected 'storage' but got '{typename}'"
        storage_type, key, location, numel = data
        if storage_type is torch.UntypedStorage:
            dtype = torch.uint8
        else:
            dtype = storage_type.dtype
        return [typename, storage_type, key, location, numel, dtype, numel * torch._utils._element_size(dtype)]

        #if key in loaded_storages:
        #    typed_storage = loaded_storages[key]
        #else:
        if True:
            #nbytes = numel * torch._utils._element_size(dtype)
            #typed_storage = functools.partial(load_tensor, dtype, nbytes, key, _maybe_decode_ascii(location))
            typed_storage = torch.TypedStorage(numel, dtype=dtype, device='meta', _internal=True)
            typed_storage._untyped_storage.__file = zip_file
            typed_storage._untyped_storage.fetch = lambda: load_tensor(
                dtype,
                numel * torch._utils._element_size(dtype),
                key,
                _maybe_decode_ascii(location)
            )

        return typed_storage

    load_module_mapping: Dict[str, str] = {
        # See https://github.com/pytorch/pytorch/pull/51633
        'torch.tensor': 'torch._tensor'
    }

    # Need to subclass Unpickler instead of directly monkey-patching the find_class method
    # because it's marked readonly in pickle.
    # The type: ignore is because mypy can't statically determine the type of this class.
    class UnpicklerWrapper(pickle_module.Unpickler):  # type: ignore[name-defined]
        # from https://stackoverflow.com/questions/13398462/unpickling-python-objects-with-a-changed-module-path/13405732
        # Lets us override the imports that pickle uses when unpickling an object.
        # This is useful for maintaining BC if we change a module path that tensor instantiation relies on.
        def find_class(self, mod_name, name):
            if type(name) is str and 'Storage' in name:
                try:
                    return StorageType(name)
                except KeyError:
                    pass
            mod_name = load_module_mapping.get(mod_name, mod_name)
            if '_rebuild_tensor' in name:
                return makeRemoteTensor(super().find_class(mod_name, name))
            return super().find_class(mod_name, name)

    # Load the data (which may in turn use `persistent_load` to load tensors)
    data_file = io.BytesIO(zip_file.get_record(pickle_file))

    unpickler = UnpicklerWrapper(data_file, **pickle_load_args)
    unpickler.persistent_load = persistent_load
    result = unpickler.load()

    torch._utils._validate_loaded_sparse_tensors()

    return result
