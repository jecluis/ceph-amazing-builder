#!/bin/bash

specfile=$1
section=$2

is_in_section=false
IFS=$'\n'
for line in $(rpmspec --parse ${specfile}); do
  [[ $line =~ ^%${section} ]] && is_in_section=true && continue
  $is_in_section && [[ $line =~ ^% ]] && break
  $is_in_section && echo $line && continue
done
