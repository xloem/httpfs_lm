# httpfs-lm

Load Git-LFS files without using disk space.

This quick batch script clones Git-LFS repositories from https://huggingface.co
and uses https://github.com/excitoon/httpfs to mount the Git-LFS files via the
network, without ever writing them to disk.

This makes it easy to clone and use models without consuming disk space for
them.

Caveats:
- Bytes will be retrieved from the network on every read, so repeated loading
  is just as slow as initial loading.
- There is presently no way to unmount the files. I use `ps -Af | grep httpfs`
  and sigkill all the listed process ids.
- A new mounted filesystem is constructed for every Git-LFS file in the passed
  revision.

Example:
```
$ ./httpfs_lm.bash cerebras/btlm-3b-8k-base@main
Cloning into 'cerebras_btlm-3b-8k-base_main'...
remote: Enumerating objects: 87, done.
remote: Counting objects: 100% (3/3), done.
remote: Compressing objects: 100% (3/3), done.
remote: Total 87 (delta 0), reused 0 (delta 0), pack-reused 84
Unpacking objects: 100% (87/87), 2.71 MiB | 10.58 MiB/s, done.
Mounting cerebras_btlm-3b-8k-base_main/pytorch_model.bin ..
Got 1 parts.
https://huggingface.co/cerebras/btlm-3b-8k-base/resolve/main/pytorch_model.bin 4.9G
...
cerebras_btlm-3b-8k-base_main/pytorch_model.bin -> /tmp/tmpzlt2mr7d/pytorch_model.bin

https://huggingface.co/cerebras/btlm-3b-8k-base mounted at cerebras_btlm-3b-8k-base_main
```

Extending this script to handle Git-LFS repositories on other hosts would just
mean ensuring the URL to the large files is correct.  For example, for GitHub I
think `/resolve/` would simply be changed to `/raw/` in the value assigned to
`httpfspath` in the script.
