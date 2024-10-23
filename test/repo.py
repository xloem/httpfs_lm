import os

from .repo_lfs import LFS
from .repo_annex import Annex

class Repo:
    def __init__(self, root):
        import dulwich.repo
        self.dulwich = dulwich.repo.Repo(root)
        self.rootdir = self.dulwich.path
        self.gitdir = self.dulwich.controldir()
        self.backends = [
            Backend(self.dulwich, self.rootdir, self.gitdir)
            for Backend in [LFS, Annex]
        ]
    def get_by_path(self, path, st):
        for backend in self.backends:
            f = backend.get_by_path(path, st)
            if f is not None:
                break
        return f
    @staticmethod
    def cmd_clone(args):
        import dulwich.cli
        dulwich.cli.cmd_clone().run(args)
