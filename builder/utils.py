import click
import shlex
import subprocess
import sys
import os
import re
from datetime import datetime as dt
from typing import List, Any, Tuple


def serror(what: str):
    return click.style(what, fg="red")


def swarn(what: str):
    return click.style(what, fg="yellow")


def sokay(what: str):
    return click.style(what, fg="green")


def sinfo(what: str):
    return click.style(what, fg="cyan")


def sdebug(what: str):
    return click.style(what, fg="white", bold=True)


def perror(what: str):
    print(serror(what))


def pwarn(what: str):
    print(swarn(what))


def pokay(what: str):
    print(sokay(what))


def pinfo(what: str):
    print(sinfo(what))


def pdebug(what: str):
    print(sdebug(what))


def _print_tree_item(
    key: str, value: Any, children: List[Any],
    indent: int = 0, prefix: str = '-', color=None
):
    indentstr = ' '*indent
    prefixstr = "{}{} ".format(indentstr, prefix)
    keystr = "{}{}:".format(prefixstr, key)
    if color:
        keystr = click.style(keystr, fg=color)

    print("{} {}".format(keystr, value))
    for x in children:
        if len(x) == 3:
            _print_tree_item(x[0], x[1], x[2],
                             indent=indent+3, prefix=prefix, color=color)
        else:
            assert len(x) == 2
            _print_tree_item(x[0], x[1], [],
                             indent=indent+3, prefix=prefix, color=color)


def print_tree(tree: List[Any], prefix: str = '-', color: str = 'cyan'):
    for key, value, children in tree:
        _print_tree_item(key, value, children, 0, prefix, color)


def _print_table_item(
    left_len: int, key: str, value: str, color: str = None
):
    indent_value: int = left_len - len(key)
    indent = ' '*indent_value
    keystr = "{}{}:".format(indent, key)
    if color:
        keystr = click.style(keystr, fg=color)
    print("{} {}".format(keystr, value))


def print_table(table: List[Any], color=None):
    max_len: int = 0
    for k, v in table:
        max_len = max(max_len, len(k))

    for k, v in table:
        _print_table_item(max_len, k, v, color)


def run_cmd(
    cmd: str,
    capture_output: bool = True
) -> Tuple[int, List[str], List[str]]:
    """ Run command

        Returns a tuple with:
         * the command's return code;
         * list of lines from stdout;
         * list of lines from stderr;

        both stdout and stderr will be empty lists if 'capture_output' is
        set to false.
    """
    out = subprocess.PIPE
    err = subprocess.PIPE
    if not capture_output:
        out = sys.stdout   # type: ignore
        err = sys.stderr   # type: ignore

    proc = subprocess.run(shlex.split(cmd), stdout=out, stderr=err)

    stdout = []
    stderr = []
    if capture_output:
        if proc.stdout:
            stdout = proc.stdout.decode("utf-8").splitlines()
        if proc.stderr:
            stderr = proc.stderr.decode("utf-8").splitlines()
    return proc.returncode, stdout, stderr


class CABError(Exception):
    def __init__(self, rc: int, msg: Any):
        _err: str = os.strerror(rc)
        _msg: str = ""
        if isinstance(msg, list):
            _msg = '\n'.join(msg)
        elif isinstance(msg, str):
            _msg = msg
        if _msg and len(_msg) > 0:
            _err += f": {_msg}"
        super().__init__(serror(_err))


# from
#  https://stackoverflow.com/questions/1094841/reusable-library-to-get-human-readable-version-of-file-size
# because I'm lazy.
def sizeof_fmt(num, suffix='B') -> str:
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)


def parse_datetime(datestr: str) -> dt:
    # podman returns timestamps that python has a hard time handling.
    # make it easier by discarding some precision.
    m = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}).*', datestr)
    assert m is not None
    assert len(m.groups()) > 0
    assert len(m.group(1)) > 0
    return dt.fromisoformat(m.group(1))
