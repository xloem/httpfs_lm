#!/usr/bin/env bash

for lmurl in "$@"
do
    if [ "${lmurl#http}" == "$lmurl" ]
    then
        lmurl="https://huggingface.co/$lmurl"
    fi
    if [ "${lmurl#*@}" == "$lmurl" ]
    then
        lmurl="${lmurl}@main"
    fi
    revision="${lmurl#*@}"
    lmurl="${lmurl%@*}"
    httpfspath="${lmurl}/resolve/${revision//\//%2F}"

    if ! type -p httpfs > /dev/null
    then
        python3 -m pip install git+https://github.com/excitoon/httpfs
    fi
    sed -i 's/print(d)/print(d, flush=True)/' $(type -p httpfs) # to process the output in a pipeline
    sed -i 's/, allow_other=True//' $(type -p httpfs) # not always supported
    lmpath="${lmurl#*//}"
    lmpath="${lmpath#*/}/$revision"
    lmpath="${lmpath//\//_}"
    if ! [ -e "$lmpath"/.git/config ]
    then
        GIT_LFS_SKIP_SMUDGE=1 git clone "$lmurl" "$lmpath"
    fi
    (
        cd "$lmpath"
        git fetch origin "$revision":"remotes/origin/$revision"
        GIT_LFS_SKIP_SMUDGE=1 git checkout "remotes/origin/$revision" -b "$revision"
        git branch --set-upstream-to=origin/"$revision" "$revision"
        GIT_LFS_SKIP_SMUDGE=1 git pull
        {
            grep --files-with-matches -r https://git-lfs.github.com/spec/v1
            find -L -type l
        } | while read filename
        do
            echo "Mounting $lmpath/$filename .."
            rm "$filename"
            httpfs "$httpfspath/$filename" | while read line
            do
                echo "$line"
                if [ "$line" == "..." ]
                then
                    read mountpath
                    ln -sf "$mountpath"/"$(basename "$filename")" "$filename"
                fi
            done &
            while ! [ -e "$filename" ]; do sleep 1; done
            echo "$lmpath/$filename -> $(readlink "$filename")"
        done
    )
    echo
    echo "$lmurl" mounted at "$lmpath"
done
wait
