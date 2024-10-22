import os

class Repo:
    GIT_LFS_MAGIC = b'version https://git-lfs.github.com/spec/v1\n'
    def __init__(self, root):
        import dulwich.repo
        self.dulwich = dulwich.repo.Repo(root)
        self.path = self.dulwich.path
        self.controldir = self.dulwich.controldir()
    def get_managed_file_size(self, path):
        # git-lfs example content:
        # version https://git-lfs.github.com/spec/v1
        # oid sha256:50a132613f0fa0c3966790abf248e1326c1496a4797e0bcc6dee65283974d258
        # size 5555937267
        fd = os.open(path, os.O_RDONLY)
        try:
            if os.read(fd, len(Repo.GIT_LFS_MAGIC)) == Repo.GIT_LFS_MAGIC:
                fields = dict([
                    entry.split(' ',1)
                    for entry in os.read(fd, 1024*1024).rstrip().decode().split('\n')
                ])
                return int(fields['size'])
        finally:
            os.close(fd)
        return None
    def get_managed_symlink_size(self, path):
        # git-annex symlink to [../../].git/annex/.../KEY_DIGEST-sKEY_SIZE--KEY_CONTENT_HASH[.ext]
        pathname = os.readlink(path)
        if '.git/annex' in pathname:
            key = os.path.basename(pathname)
            prefix, hash = key.split('--',1)
            digest, sizestr = prefix.split('-',1)
            return int(sizestr[1:])
        else:
            return None
    @staticmethod
    def cmd_clone(args):
        import dulwich.cli
        dulwich.cli.cmd_clone().run(args)
