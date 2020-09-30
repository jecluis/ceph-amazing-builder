import click
import subprocess
import shlex
import json
import re
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

class ContainerImageName:
	_remote: str
	_repo: str
	_name: str
	_tag: str

	def __init__(self, remote, repo, name, tag):
		self._remote = remote
		self._repo = repo
		self._name = name
		self._tag = tag

	@property
	def name(self):
		return self._name
	
	@property
	def tag(self):
		return self._tag

	def __str__(self):
		return f"{self._remote}/{self._repo}/{self._name}:{self._tag}"


class ContainerImage:
	_hashid: str
	_name: str
	_names: List[ContainerImageName]
	_tags: List[str]
	_size: float

	def __init__(self, hashid: str,
	             names: List[ContainerImageName], size: int):
		self._hashid: str = hashid[:12]
		self._names: List[ContainerImageName] = names
		self._tags: List[str] = self._get_tags()
		self._size: float = size


	def _get_tags(self):
		tags: List[str] = []
		name: ContainerImageName
		for name in self._names:
			tags.append(name._tag)
		return tags


	def has_tag(self, tag: str) -> bool:
		return tag in self._tags

	def print(self):
		latest: str = ""
		if 'latest' in self._tags:
			latest = click.style("(latest)", fg="yellow")
		print("{} {} ({}) {}".format(
			click.style(f"- id:", fg="cyan"), self._hashid,
			            sizeof_fmt(self._size), latest))
		for name in self._names:
			print("{} {}".format(click.style("  - name:", fg="cyan"), name))


	def __str__(self) -> str:
		return f"{self._hashid} {self._names}"

	
	def get_latest_name(self) -> str:
		name: ContainerImageName
		for name in self._names:
			if name.tag == "latest":
				return str(name)
		return None


	@property
	def size(self) -> int:
		return self._size

	
	def get_size_str(self) -> str:
		return sizeof_fmt(self._size)


class Containers:
	def __init__(self):
		pass

	@classmethod
	def _exists(cls, type: str, vendor: str, release: str):
		pass


	@classmethod
	def parse_image_name(cls, namestr: str) -> ContainerImageName:
		if not namestr or len(namestr) == 0:
			return None

		matchstr = r"^([.-_\d\w]+)/(.*)/([-_\d\w]+):([-_\d\w]+)$"
		match = re.match(matchstr, namestr)
		if not match:
			return None
		if len(match.groups()) < 4:
			return None

		remote = match.group(1)
		repo = match.group(2)
		img_name = match.group(3)
		tag = match.group(4)
		return ContainerImageName(remote, repo, img_name, tag)


	@classmethod
	def find_base_build_image(cls, vendor: str, release: str) -> Optional[str]:
		cmd = f"podman images --format json cab/build/{vendor}:{release}"
		proc = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE)
		if proc.returncode != 0:
			return None
		# check name matches
		images_dict = json.loads(proc.stdout)
		for img in images_dict:
			for n in img['Names']:
				img_name = cls.parse_image_name(n)
				if img_name.name == vendor and img_name.tag == release:
					return str(img_name)
		return None		


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
	def find_build_images(cls, buildname="") -> List[ContainerImage]:
		cmd = f"podman images --format json cab-builds/{buildname}"
		proc = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE)
		images_dict = json.loads(proc.stdout)
		got_imgs: List[str] = []
		imgs: List[ContainerImage] = []
		for image_entry in images_dict:
			image_id: str = image_entry['Id']
			if image_id in got_imgs:
				continue
			got_imgs.append(image_id)
			names: List[ContainerImageName] = []
			for n in image_entry['Names']:
				img_name = cls.parse_image_name(n)
				if img_name.name != buildname:
					# print(f"img does not match: ")
					continue
				names.append(img_name)
			imgs.append(ContainerImage(image_id, names, image_entry['Size']))
		return imgs

	@classmethod
	def find_build_image_latest(cls, name: str):
		imgs: List[ContainerImage] = cls.find_build_images(name)
		for image in imgs:
			if image.has_tag('latest'):
				return image
		return None

	@classmethod
	def has_build_image(cls, name: str, tag="latest"):
		imgs: List[ContainerImage] = cls.find_build_images(name)
		for image in imgs:
			if image.has_tag(tag):
				return True
		return False
		

	@classmethod
	def run_shell(cls, name: str):
		latest: ContainerImage = cls.find_build_image_latest(name)
		if not latest:
			return False
		
		cmd = f"podman run -it {latest._hashid} /bin/bash"
		subprocess.run(shlex.split(cmd))		
		return True


	@classmethod
	def get_build_name(cls, buildname: str):
		return f"cab-builds/{buildname}"

	@classmethod
	def get_build_name_latest(cls, buildname: str):
		img: ContainerImage = cls.find_build_image_latest(buildname)
		if not img:
			return None
		return img.get_latest_name()