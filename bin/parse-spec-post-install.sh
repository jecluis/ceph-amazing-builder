#!/bin/bash

handle_attr() {
  arg1="$(echo $1 | cut -f1 -d' ')"
  arg2="$(echo $1 | cut -f2 -d' ')"
  arg3="$(echo $1 | cut -f3 -d' ')"

  attr="${arg1}"
  file="${arg2}"
  [[ -n "${arg3}" ]] && file="${arg3}"

  mode="$(echo ${arg1} | cut -f1 -d',')"
  user="$(echo ${arg1} | cut -f2 -d',')"
  group="$(echo ${arg1} | cut -f3 -d',')"

  echo "chmod ${mode} ${file}"
  if [[ "${user}" != "-" && "${group}" != "-" ]]; then
    echo "chown ${user}:${group} ${file}"
  fi

  # echo "> ${attr} @ ${file}"
}


if [[ $# -lt 1 ]]; then
  echo "usage: $0 <specfile>"
  exit 1
fi

specfile="${1}"
[[ -z "${specfile}" ]] && echo "specfile not specified" && exit 1
[[ ! -e "${specfile}" ]] && echo "specfile does not exist" && exit 1


cat << EOF
#!/bin/bash

echo "run post-install requirements for image"

EOF

IFS=$'\n'

in_pre_section=false
for line in $(rpmspec --parse ${specfile}); do
  # echo "> $line"

  if [[ $line =~ ^%preun || $line =~ ^%prep ]]; then
    if $in_pre_section ; then
      in_pre_section=false
    fi
    continue

  elif [[ $line =~ ^%pre ]]; then
    # echo "in %pre section"
    in_pre_section=true
    continue
  elif [[ $line =~ ^% ]]; then
    if $in_pre_section ; then
      in_pre_section=false
      # echo "out of pre section at ${line}"
    fi
    continue
  elif [[ $line =~ ^exit ]]; then
    continue
  fi

  if ! $in_pre_section ; then
    continue
  fi
  echo "$line"

done

for attr in $(rpmspec --parse ${specfile} | grep '^%attr' |
    sed 's/%attr(\(.*\)) \(.*\)$/\1 \2/g'); do
  handle_attr ${attr}
done
