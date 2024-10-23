import errno, os, sys, threading
import fuse
from . import repo

class Interface(fuse.Operations):
    def __init__(self, repo, mountpath):
        self.repo = repo
        self.lock = threading.Lock()
        self.external_fds = []
        self.external_fd_next = None

    def _external_fd_alloc(self, obj):
        with self.lock:
            if self.next_external_fd is not None:
                fd = self.external_fd_next
                self.external_fd_next = self.external_fds[fd]
                self.external_fds[fd] = obj
            else:
                fd = len(self.external_fds)
                self.external_fds.append(obj)
        fd = -fd - 1
        return fd
    def _external_fd_free(self, fd):
        fd = -fd - 1
        with self.lock:
            self.external_fds[fd] = self.external_fd_next
            self.external_fd_next = fd
    def _external_get(self, path, st, fd):
        if fd is not None:
            if fd < 0:
                return self.external_fds[fd]
            else:
                return None
        else:
            return self.repo.get_by_path(path, st)
    
    def _full_path(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]
        return os.path.join(self.repo.rootdir, partial)


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
        external = self._external_get(full_path, st, fi.fh)
        if external is not None:
            stat['st_size'] = external.size
        return stat

    def open(self, path, flags, fi):
        full_path = self._full_path(path)
        external = self.repo.get_by_path(full_path)
        if external is not None:
            fi.fh = self._external_fd_alloc(external)
        else:
            fi.fh = os.open(full_path, flags)
        return 0

    def read(self, path, size, offset, fi):
        fh = fi.fh
        if fh >= 0:
            with self.lock:  # Ensure thread-safe reads
                os.lseek(fh, offset, os.SEEK_SET)
                return os.read(fh, size)
        else:
            external = self._external_get(path, None, fh)

    def readdir(self, path, fi):
        full_path = self._full_path(path)
        dirents = ['.', '..'] + os.listdir(full_path)
        for r in dirents:
            yield r

    def readlink(self, path):
        pathname = os.readlink(self._full_path(path))
        if pathname.startswith("/"):
            return os.path.relpath(pathname, self.repo.path)
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
        if args.help or not args.mountpoint:
            try:
                FUSEWithRawArgs(None, parser.prog + ' mount [repo_path]', '--help')
            except RuntimeError as err:
                sys.exit(*err.args)
        else:
            repo_path = os.path.abspath(args.repo_path)
            mountpoint = os.path.abspath(args.mountpoint or args.repo_path)
            repository = repo.Repo(repo_path)
            backend = Interface(repository, mountpoint)
            FUSEWithRawArgs(backend, parser.prog, mountpoint, raw_fi=True, *args.fuse_args)
