# httpfs-lm

Load Git-LFS files without using disk space.

This quick bash script clones Git-LFS repositories from https://huggingface.co
and uses https://github.com/excitoon/httpfs to mount the Git-LFS files via the
network with FUSE, without ever writing them to disk.

This makes it easy to clone and use models without consuming disk space for
them.

Caveats:
- Bytes will be retrieved from the network on every read, so repeated loading
  is just as slow as initial loading.
- There is presently no way to unmount the files. I use `ps -Af | grep httpfs`
  and sigkill all the listed process ids.
- A new mounted filesystem and two processes are constructed for every Git-LFS
  file.
- I have not tested this much, and used it with a tiny model.

Example:
```
$ ./httpfs_lm.bash cerebras/btlm-3b-8k-base@main
Cloning into 'cerebras_btlm-3b-8k-base_main'...
remote: Enumerating objects: 87, done.
remote: Counting objects: 100% (60/60), done.
remote: Compressing objects: 100% (60/60), done.
remote: Total 87 (delta 27), reused 0 (delta 0), pack-reused 27
Unpacking objects: 100% (87/87), 2.71 MiB | 9.20 MiB/s, done.
fatal: a branch named 'main' already exists
branch 'main' set up to track 'origin/main'.
Already up to date.
Mounting cerebras_btlm-3b-8k-base_main/pytorch_model.bin ..
Got 1 parts.
https://huggingface.co/cerebras/btlm-3b-8k-base/resolve/main/pytorch_model.bin 4.9G
...
cerebras_btlm-3b-8k-base_main/pytorch_model.bin -> /tmp/tmp0y3337k4/pytorch_model.bin

https://huggingface.co/cerebras/btlm-3b-8k-base mounted at cerebras_btlm-3b-8k-base_main
```

Extending this script to handle Git-LFS repositories on other hosts would just
mean ensuring the URL to the large files is correct.  For example, for GitHub I
think `/resolve/` would simply be changed to `/raw/` in the value assigned to
`httpfspath` in the script.
