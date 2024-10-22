class Repo:
    def __init__(self, root):
        import dulwich.repo
        self.dulwich = dulwich.repo.Repo(root)
        self.path = self.dulwich.path
        self.controldir = self.dulwich.controldir()
    @staticmethod
    def cmd_clone(args):
        import dulwich.cli
        dulwich.cli.cmd_clone().run(args)
