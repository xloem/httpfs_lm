import errno, os, sys, threading
import fuse
from . import repo

class Interface(fuse.Operations):
    XATTR_PFX = 'user.'
    def __init__(self, repo, mountpath):
        self._repo = repo
        self._lock = threading.Lock()
        self._external_fds = []
        self._external_fd_next = None

    def _external_fd_to_idx(self, fd):
        return fd - 0x10000
    def _external_idx_to_fd(self, idx):
        return idx + 0x10000
    def _external_fd_check(self, fd):
        return fd >= 0x10000
    def _external_fd_alloc(self, obj):
        with self._lock:
            if self._external_fd_next is not None:
                idx = self._external_fd_next
                self._external_fd_next = self._external_fds[idx]
                self._external_fds[idx] = obj
            else:
                idx = len(self._external_fds)
                self._external_fds.append(obj)
        return self._external_idx_to_fd(idx)
    def _external_fd_free(self, fd):
        idx = self._external_fd_to_idx(fd)
        with self._lock:
            self._external_fds[idx] = self._external_fd_next
            self._external_fd_next = idx
    def _external_get(self, path, st, fd):
        if fd is not None:
            if self._external_fd_check(fd):
                return self._external_fds[self._external_fd_to_idx(fd)]
            else:
                return None
        else:
            return self._repo.get_by_path(path, st)
    
    def _full_path(self, path):
        assert path[0] == '/'
        if len(path) == 1:
            return '.'
        else:
            return path[1:]

    def getattr(self, path, fi):
        # this returns a dict
        # the cross-platform attributes of fuse.c_stat are:
        # st_dev, st_ino, st_nlink, st_mode, st_uid, st_gid, st_rdev, st_atimespec, st_mtimespec, st_ctimespec, st_size, st_blocks, st_blksize
        full_path = self._full_path(path)
        try:
            st = os.lstat(full_path)
        except FileNotFoundError:
            raise fuse.FuseOSError(errno.ENOENT)
        stat = dict(
            st_mode=st[0], st_ino=st[1], st_dev=st[2], st_nlink=st[3],
            st_uid=st[4], st_gid=st[5], st_size=st[6], st_atime=st[7],
            st_mtime=st[8], st_ctime=st[9]
        )
        external = self._external_get(full_path, st, fi and fi.fh)
        if external is not None:
            stat['st_size'] = external.size
        return stat

    def listxattr(self, path):
        full_path = self._full_path(path)
        external = self._repo.get_by_path(full_path)
        if external is not None:
            return [
                self.XATTR_PFX + name
                for name, val in external.__dict__.items()
                if type(val) in [str,int]
            ]
        else:
            return []

    def getxattr(self, path, name):
        if name[:len(self.XATTR_PFX)] == self.XATTR_PFX:
            full_path = self._full_path(path)
            external = self._repo.get_by_path(full_path)
            if external is not None:
                try:
                    return str(getattr(external, name[len(self.XATTR_PFX):])).encode()
                except AttributeError:
                    pass
        raise fuse.FuseOSError(fuse.errno.ENODATA)

    def open(self, path, fi):
        full_path = self._full_path(path)
        external = self._repo.get_by_path(full_path)
        if external is not None:
            fi.fh = self._external_fd_alloc(external)
            external.open()
        else:
            fi.fh = os.open(full_path, fi.flags)
        return 0

    def read(self, path, size, offset, fi):
        fh = fi.fh
        external = self._external_get(path, None, fh)
        if external is None:
            with self._lock:  # Ensure thread-safe reads
                os.lseek(fh, offset, os.SEEK_SET)
                return os.read(fh, size)
        else:
            return external.read(size, offset)

    def readdir(self, path, fi):
        full_path = self._full_path(path)
        dirents = ['.', '..'] + os.listdir(full_path)
        for r in dirents:
            yield r

    def readlink(self, path):
        pathname = os.readlink(self._full_path(path))
        if pathname.startswith("/"):
            return os.path.relpath(pathname, self._repo.path)
        else:
            return pathname

class FUSEWithRawArgs(fuse.FUSE):
    def __init__(self, operations, *raw_args, raw_fi=False, encoding='utf-8'):
        from fuse import ctypes, fuse_operations, _libfuse, partial, signal, SIGINT, SIG_DFL

        self.operations = operations
        self.raw_fi = raw_fi
        self.encoding = encoding
        self.__critical_exception = None
        self.use_ns = getattr(operations, 'use_ns', False)
        
        raw_args = [arg.encode(encoding) for arg in raw_args]
        argv = (ctypes.c_char_p * len(raw_args))(*raw_args)

        fuse_ops = fuse_operations()
        for ent in fuse_operations._fields_:
            name, prototype = ent[:2]

            check_name = name

            if check_name in ["ftruncate", "fgetattr"]:
                check_name = check_name[1:]

            val = getattr(operations, check_name, None)
            if val is None:
                continue

            if hasattr(prototype, 'argtypes'):
                val = prototype(partial(self._wrapper, getattr(self, name)))

            setattr(fuse_ops, name, val)

        try:
            old_handler = signal(SIGINT, SIG_DFL)
        except ValueError:
            old_handler = SIG_DFL

        err = _libfuse.fuse_main_real(
            len(raw_args), argv, ctypes.pointer(fuse_ops),
            ctypes.sizeof(fuse_ops),
            None)

        try:
            signal(SIGINT, old_handler)
        except ValueError:
            pass

        del self.operations
        if self.__critical_exception:
            raise self.__critical_exception
        if err:
            raise RuntimeError(err)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Mount repository")
    subparsers = parser.add_subparsers(dest="command")

    # Clone commnd
    clone_parser = subparsers.add_parser("clone", help="Clone a repository", add_help=False)
    clone_parser.add_argument("clone_args", nargs=argparse.REMAINDER)
    clone_parser.add_argument('-h', '--help', action='store_true')

    # Mount command
    mount_parser = subparsers.add_parser("mount", help="Mount a repository", add_help=False)
    mount_parser.add_argument('repo_path', nargs='?')
    mount_parser.add_argument('mountpoint', nargs='?')
    mount_parser.add_argument('fuse_args', nargs=argparse.REMAINDER)
    mount_parser.add_argument('-h', '--help', action='store_true')

    args = parser.parse_args()
    if args.command == "clone":
        # Pass arguments to Repo.cmd_clone for cloning
        if args.help:
            sys.argv[0] = parser.prog + ' clone'
            repo.Repo.cmd_clone(['--help'])
        else:
            repo.Repo.cmd_clone(args.clone_args)

    elif args.command == "mount":
        if args.mountpoint is None:
            args.fuse_args[:0] = ['-o', 'nonempty']
            args.mountpoint = args.repo_path
        if args.help or not args.mountpoint:
            try:
                FUSEWithRawArgs(None, parser.prog + ' mount [repo_path]', '--help')
            except RuntimeError as err:
                sys.exit(*err.args)
        else:
            mountpoint = os.path.abspath(args.mountpoint)
            os.chdir(args.repo_path)
            repository = repo.Repo('.')
            backend = Interface(repository, mountpoint)
            FUSEWithRawArgs(backend, parser.prog, mountpoint, raw_fi=True, *args.fuse_args)
