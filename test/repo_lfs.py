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


