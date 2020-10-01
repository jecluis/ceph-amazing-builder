import click
from typing import List, Any

def serror(what: str):
	return click.style(what, fg="red")

def swarn(what: str):
	return click.style(what, fg="yellow")

def sokay(what: str):
	return click.style(what, fg="green")

def sinfo(what: str):
	return click.style(what, fg="cyan")

def perror(what: str):
	print(serror(what))

def pwarn(what: str):
	print(swarn(what))

def pokay(what: str):
	print(sokay(what))

def pinfo(what: str):
	print(sinfo(what))


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