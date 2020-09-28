import click
import subprocess
import shlex
import json
from typing import List, Tuple, Optional


# from
#  https://stackoverflow.com/questions/1094841/reusable-library-to-get-human-readable-version-of-file-size
# because I'm lazy.
def sizeof_fmt(num, suffix='B'):
	for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
		if abs(num) < 1024.0:
			return "%3.1f%s%s" % (num, unit, suffix)
		num /= 1024.0
	return "%.1f%s%s" % (num, 'Yi', suffix)


class ContainerImage:
	_hashid: str
	_names: List[str]
	_tags: List[str]
	_size: float
	def __init__(self, hashid: str, names: List[str], size: int):
		self._hashid: str = hashid[:12]
		self._names: List[str] = names
		self._tags: List[str] = self._get_tags()
		self._size: float = size

	def _get_tags(self):
		tags: List[str] = []
		for name in self._names:
			fields = name.split(':')
			if (len(fields) < 2): continue
			tags.append(fields[1])
		return tags

	def print(self):
		latest: str = ""
		if 'latest' in self._tags:
			latest = click.style("(latest)", fg="yellow")
		print("{} {} ({}) {}".format(
			click.style(f"- id:", fg="cyan"), self._hashid,
			            sizeof_fmt(self._size), latest))
		for name in self._names:
			print("{} {}".format(click.style("  - name:", fg="cyan"), name))


class Containers:
	def __init__(self):
		pass

	@classmethod
	def _exists(cls, type: str, vendor: str, release: str):
		pass


	@classmethod
	def find_release_base_image(
	    cls,
	    vendor: str,
	    release: str
	) -> Tuple[Optional[str], Optional[str]]:
		cmd = "podman images --format json"
		proc = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE)
		images_json = json.loads(proc.stdout)
		for image_entry in images_json:
			# print(image_entry['Names'])
			image_id: str = image_entry['Id']
			name: str
			for name in image_entry['Names']:
				if name.endswith(f'cab/base/release/{vendor}:{release}'):
					# print(f"found {name}")
					return name, image_id
		return None, None

	@classmethod
	def find_build_images(cls, name="") -> List[ContainerImage]:
		cmd = f"podman images --format json {name}"
		proc = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE)
		images_dict = json.loads(proc.stdout)
		got_imgs: List[str] = []
		imgs: List[ContainerImage] = []
		for image_entry in images_dict:
			image_id: str = image_entry['Id']
			if image_id in got_imgs:
				continue
			got_imgs.append(image_id)
			names: List[str] = image_entry['Names']
			imgs.append(ContainerImage(image_id, names, image_entry['Size']))
		return imgs

	@classmethod
	def find_build_image_latest(cls, name: str):
		imgs: List[ContainerImage] = cls.find_build_images(name)
		for image in imgs:
			if 'latest' in image._tags:
				return image
		return None

	@classmethod
	def run_shell(cls, name: str):
		latest: ContainerImage = cls.find_build_image_latest(name)
		if not latest:
			return False
		
		cmd = f"podman run -it {latest._hashid} /bin/bash"
		subprocess.run(shlex.split(cmd))		
		return True
