import os

class Annex:
    LINK_PFX = '.git/annex/objects/'
    def __init__(self, dulwich, workdir, controldir):
        self.dulwich = dulwich
        self.workdir = workdir
        self.controldir = controldir
    def get_by_path(self, path, st, fd):
        if st is None:
            st = os.lstat(path)
        if not st.st_mode & 0o770000 == 0o120000:
            return None
        link = os.readlink(path)
        if not self.LINK_PFX in link:
            return None
        return AnnexFile(path)

        
class AnnexFile:
    def __init__(self, annex, path):
        self.path = path
        self.key = os.path.basename(link)
        key, *_ = self.key.split('.',1)
        pfx, self.digest = key.split('--',1)
        self.algo, sizestr = pfx.split('-',1)
        self.size = int(sizestr[1:])
    def open(self):
        assert os.path.exists(self.path)
        ...
