# https://github.com/git-lfs/git-lfs/blob/main/docs/spec.md
# https://github.com/git-lfs/git-lfs/blob/main/docs/api/server-discovery.md
# https://github.com/git-lfs/git-lfs/blob/a577e336ebdccfd312b6006c880f010b5d3fe796/lfsapi/auth.go#L309

# POINTER
# version https://git-lfs.github.com/spec/v1
# oid sha256:4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393
# size 12345
# (ending \n)

# LOCAL
# .git/lfs/objects/OID[0:2]/OID[2:4]/OID
# .git/lfs/objects/4d/7a/4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393

# REMOTE
# [remote-url].git/info/lfs, git config lfs.url, git config remote.{name}.lfsurl, .lfsconfig
# ssh [{user}@]{server} git-lfs-authenticate {foo/bar.git} {upload|download}
#  { "href": "https://lfs-server.com/foo/bar", "header": { "Authorization": "RemoteAuth some-token" }, "expires_in": 86400 }
# ~/.git-credentials or if not exist, then $XDG_CONFIG_HOME/git/credentials  via git-credential-store. there are more credential sources.
#  .git-credentials format: https://user:pass@host.com this format is allowed in git remote urls
# Authorization: Basic {base64("user:pass")}

import base64, concurrent.futures, datetime, os, threading, time, datetime
import requests

class LFS:
    MAGIC = b'version https://git-lfs.github.com/spec/v1\n'
    MIME = 'application/vnd.git-lfs+json'
    class ErrorCode:
        SUCCESS = 200
        CREDENTIALS = 401
        ACCESS = 403
        EXIST = 404
        MIME = 406
        ALGO = 409
        REMOVED = 410
        QUANTITY = 413
        VALIDATION = 422
        RATE = 429
        UNIMPLEMENTED = 501
        CAPACITY = 507
        BANDWIDTH = 509
        descriptions = {
            SUCCESS: "Success.",
            CREDENTIALS: "The authentication credentials are needed, but were not sent. Git LFS will attempt to get the authentication for the request and retry immediately.",
            ACCESS: "The user has read, but not write access. Only applicable when the operation in the request is \"upload.\"",
            EXIST: "The Repository or object does not exist for the user.",
            MIME: "The Accept header needs to be application/vnd.git-lfs+json.",
            ALGO: "The specified hash algorithm disagrees with the server's acceptable options.",
            REMOVED: "The object was removed by the owner.",
            QUANTITY: "The batch API request contained too many objects or the request was otherwise too large.",
            VALIDATION: "Validation error with one or more of the objects in the request. This means that none of the requested objects to upload are valid.",
            RATE: "The user has hit a rate limit with the server. Though the API does not specify any rate limits, implementors are encouraged to set some for availability reasons.",
            UNIMPLEMENTED: "The server has not implemented the current method. Reserved for future use.",
            CAPACITY: "The server has insufficient storage capacity to complete the request.",
            BANDWIDTH: "The bandwidth limit for the user or repository has been exceeded. The API does not specify any bandwidth limit, but implementors may track usage.",
        }
    def __init__(self, dulwich, workdir, controldir, lfs_batch_urls=None, session=None):
        self.dulwich = dulwich
        self.workdir = workdir
        self.controldir = controldir
        self._lock = threading.Lock()
        self._files = {}
        self._auths = {}
        self.batch_urls = lfs_batch_urls
        self.session = session

    def _populate_batch_urls(self):
        batch_urls = []
        config = self.dulwich.get_config()
        if self.session is None:
            self.session = requests.Session()
        for section_tuple in config.sections():
            if section_tuple[0] == b'remote':
                try:
                    remote_url = config.get(section_tuple, b'url').decode()
                    batch_urls.append(self._remote_url_to_batch_url(remote_url))
                except KeyError:
                    continue
        batch_url_proto_hosts = [
            [url, proto.encode(), host.encode()]
            for url in batch_urls
            for [proto, _, host, path] in [url.split('/',3)]
        ]
        with open(os.path.expanduser('~/.git-credentials'), 'rb') as fh:
            for line in fh.read().split(b'\n'):
                for url, proto, host in batch_url_proto_hosts:
                    if line.startswith(proto) and line.endswith(host):
                        auth = line[len(proto)+2:-len(host)-1]
                        token = base64.b64encode(auth).decode()
                        self._auths[url] = {
                            "Authorization": "Basic " + token
                        }
                        del auth, token
        working_batch_urls = []
        for batch_url in batch_urls:
            try:
                self._batch(batch_url)
                working_batch_urls.append(batch_url)
            except requests.JSONDecodeError:
                continue
        assert working_batch_urls
        self.batch_urls = working_batch_urls
        return self.batch_urls

    @staticmethod
    def _remote_url_to_batch_url(url):
        if url[-1] == '/':
            url = url[:-1]
        if url[-3:] == '.git':
            url = url[:-3]
        return url + '.git/info/lfs/objects/batch'
    
    def get_by_path(self, path, st, fd):
        pointer = self._pointer(path, fd)
        if pointer is None:
            return None;
        oid_short = pointer['oid'].split(':',1)[-1]
        file = self._files.get(oid_short)
        if file is None:
            file = LFSFile(self, path, pointer)
            assert file.oid_short == oid_short
            self._files[file.oid_short] = file
        return file
    
    def _batch(self, batch_url, *oid_size_pairs, operation='download', transfers=None, ref=None, hash_algo=None):
        headers = {
            **self._auths.get(batch_url, {}),
            'Accept': self.MIME,
            'Content-Type': self.MIME,
        }
        data = '{"operation":"'+operation+'"'
        if transfers is not None:
            data += ',"transfers":['+','.join(['"'+tx+'"' for tx in transfers])+']'
        if ref is not None:
            data += ',"ref":{"name":"' + ref + '"}'
        data += ',"objects":['
        for oid, size in oid_size_pairs:
            idx = oid.find(':')
            if idx != -1:
                oid_hash_algo = oid[:idx]
                oid = oid[idx+1:]
                if hash_algo is None:
                    hash_algo = oid_hash_algo
                else:
                    assert hash_algo == oid_hash_algo
            data += '{"oid":"'+oid+'","size":'+str(size)+'}'
        data += ']'
        if hash_algo not in [None, 'sha256']:
            data += ',"hash_algo":"' + hash_algo + '"'
        data += '}'
        res_http = self.session.post(batch_url, headers=headers, data=data)
        res_json = res_http.json()
        if 'message' in res_json:
            raise LFSException(res_http.status_code, **res_json, request=res_http.request, response=res_http, document=res_json)
        if not 'objects' in res_json or type(res_json['objects']) is not list:
            raise requests.JSONDecodeError('objects field not found or not a list', res_http.content, None)
        res_json.setdefault('transfer','basic')
        res_json.setdefault('hash_algo','sha256')
        return [res_http, res_json]
    def _fetch_hrefs_for(self, batch_url, ref=None, hash_algo=None, **files):
        http, res = self._batch(batch_url, *[[file.oid_short, file.size] for file in files.values()], operation='download', ref=ref, hash_algo=hash_algo)
        auth = self._auths.get(batch_url,{})
        result = {}
        for object in res['objects']:
            oid_short = object['oid']
            file = files[oid_short]
            if 'error' in object:
                error = LFSException(**object['error'], response=http, request=http.request, document=object)
                file.batch_urls.remove(batch_url)
                file.errors[batch_url] = error
            else:
                assert file.size == object['size']
                # if not object.get('authenticated') then credentials are not yet correct
                action = object['actions']['download']
                url = action['href']
                file.update_href(url, action.get('expires_at',None), **auth, **action.get('header',{}))
            result[file.oid_short] = file
        return result
    def _pointer(self, path, fd):
        if fd is None:
            read_fd = os.open(path, os.O_RDONLY)
        else:
            read_fd = fd
            start = os.lseek(fd, os.SEEK_CUR)
            assert start == 0 # feel free to change the logic around this
        try:
            if os.read(read_fd, len(self.MAGIC)) != self.MAGIC:
                return None
            return dict([
                entry.split(' ',1)
                for entry in os.read(read_fd, 1024*1024)[:-1].decode().split('\n')
            ])
        except:
            return None
        finally:
            if read_fd != fd:
                os.close(read_fd)
            else:
                os.lseek(fd, start)

class LFSFile:
    def __init__(self, lfs, path, pointer):
        self.lfs = lfs
        self.path = path
        self.oid_full = pointer['oid']
        self.hash_algo, self.oid_short = self.oid_full.split(':',1)
        self.lfs_path = os.path.join('lfs', 'objects', self.oid_short[:2], self.oid_short[2:4], self.oid_short)
        self.size = int(pointer['size'])
        self.expires_at = 0
        self.batch_urls = None
        self.errors = {}
        self.lock = threading.Lock()
    def open(self):
        with self.lock:
            lfs_path = os.path.join(self.lfs.controldir, self.lfs_path)
            if not os.path.exists(lfs_path):
                if self.batch_urls is None:
                    with self.lfs._lock:
                        self.batch_urls = set(self.lfs.batch_urls or self.lfs._populate_batch_urls())
                while self.expired():
                    self.lfs._fetch_hrefs_pump.add(self).result()
                self.fd = None
            else:
                self.fd = os.open(lfs_path, os.O_RDONLY)
    def close(self):
        os.close(self.fd)
    def read(self, size, offset):
        if self.fd is not None:
            with self.lock:
                os.lseek(self.fd, offset, os.SEEK_SET)
                return os.read(self.fd, size)
        else:
            resp = self.lfs.session.get(self.href, headers={**self.headers, 'Range': 'bytes='+str(offset)+'-'+str(offset+size-1)})
            return resp.content
        
    def update_href(self, href, expires_at, **headers):
        self.href = href
        if type(expires_at) is str:
            expires_at = int(datetime.datetime.fromisoformat(expires_at))
        self.expires_at = expires_at
        self.headers = headers
    def expired(self):
        return self.expires_at is not None and time.time() > self.expires_at

class LFSException(RuntimeError):
    def __init__(self, code, message, request_id=None, documentation_url=None, request=None, response=None, document=None):
        self.code = code
        self.message = message
        self.request_id = request_id
        self.documentation_url = documentation_url
        self.request = request
        self.response = response
        self.document = document
        super().__init__(code, message, request_id, documentation_url, request, response, document)

class _FetchHREFsPump:
    def __init__(self, repo):
        self.repo = repo
        self.queue = []
        self.fut = None
        super().__init__()
    def add(self, *files):
        with self.repo._lock:
            self.queue.extend(files)
            if self.fut is None:
                self.fut = concurrent.futures.Future()
                self.thread = threading.Thread(target=self._run)
                self.thread.start()
            return self.fut
    def _run(self):
        while True:
            with self.repo._lock:
                chunk = self.queue
                if not len(chunk):
                    self.fut = None
                    break
                fut = self.fut
                self.queue = []
                self.fut = concurrent.futures.Future()
            chunk = {file.oid_short:file for file in chunk}
            all_oids = set(chunk)
            hash_algo_batch_url_oids = {}
            for file in chunk.values():
                for batch_url in file.batch_urls:
                    key = (file.hash_algo, batch_url)
                    entry = hash_algo_batch_url_oids.get(key)
                    if entry is None:
                        entry = set()
                        hash_algo_batch_url_oids[key] = entry
                    entry.add(file.oid_short)
            (hash_algo, batch_url), oids = max(hash_algo_batch_url_oids.items(), key=lambda item:len(item[1]))
            self.add(*[chunk.pop(oid) for oid in (all_oids - oids)])
            try:
                result = self.repo._fetch_hrefs_for(batch_url, hash_algo=hash_algo, **chunk)
                fut.set_result(result)
            except Exception as exc:
                fut.set_exception(exc)
