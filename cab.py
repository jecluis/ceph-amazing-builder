#!/usr/bin/python3
import click
import json
import errno
import sys
import subprocess
import shlex
import shutil
from appdirs import user_config_dir
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List


# from
#  https://stackoverflow.com/questions/1094841/reusable-library-to-get-human-readable-version-of-file-size
# because I'm lazy.
def sizeof_fmt(num, suffix='B'):
	for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
		if abs(num) < 1024.0:
			return "%3.1f%s%s" % (num, unit, suffix)
		num /= 1024.0
	return "%.1f%s%s" % (num, 'Yi', suffix)


class Config:

	_config_dir: Path = None
	_build_config_dir: Path = None
	_has_config: bool = False

	_ccache_dir: Path = None
	_builds_dir: Path = None


	def __init__(self):
		config_dir = user_config_dir('cab')
		self._config_dir = Path(config_dir)
		self._config_dir.mkdir(0o755, exist_ok=True)
		self._build_config_dir = self._config_dir.joinpath('builds')
		self._build_config_dir.mkdir(0o755, exist_ok=True)
		self._has_config = self._read_config()


	def _read_config(self) -> bool:
		config_path = self._config_dir.joinpath('config.json')
		# print(f"config path: {config_path}")
		if not config_path.exists():
			return False
	
		# print("reading config file")
		with config_path.open('r') as fd:
			config_dict: Dict[str, str] = json.load(fd)
			if 'ccache' in config_dict:
				self._ccache_dir = Path(config_dict['ccache'])
			if 'builds' in config_dict:
				self._builds_dir = Path(config_dict['builds'])

		if not self._builds_dir:
			return False
		return True


	def has_config(self):
		return self._has_config

	def get_config_path(self) -> str:
		return str(self._config_dir.joinpath('config.json'))

	def get_ccache_dir(self) -> Path:
		return self._ccache_dir
	
	def get_builds_dir(self) -> Path:
		return self._builds_dir

	def set_ccache_dir(self, ccache_str: str):
		self._ccache_dir = Path(ccache_str).expanduser()

	def set_builds_dir(self, builds_dir: str):
		self._builds_dir = Path(builds_dir).expanduser()

	
	def _write_config(self):
		assert self._config_dir.exists()
		config_file = 'config.json'
		d = {
				'ccache': str(self._ccache_dir),
				'builds': str(self._builds_dir)
		}
		path = self._config_dir.joinpath(config_file)
		self._write_config_file(d, path)


	def _write_config_file(self, d: Dict[str, Any], path: Path):
		with path.open('w') as fd:
			json.dump(d, fd)


	def commit(self):
		self._write_config()

	def _get_build_config_path(self, name: str) -> Path:
		return self._build_config_dir.joinpath(f'{name}.json')
	
	def build_exists(self, name: str) -> bool:
		return self._get_build_config_path(name).exists()

	def get_build_config(self, name: str) -> Dict[str, Any]:
		if not self.build_exists(name):
			raise UnknownBuildError(name)

		path = self._get_build_config_path(name)
		build_config = None
		with path.open('r') as fd:
			build_config = json.load(fd)
		return build_config

	def write_build_config(self, name: str, conf_dict: Dict[str, Any]):
		assert name
		assert conf_dict		
		path = self._get_build_config_path(name)
		self._write_config_file(conf_dict, path)

	def get_builds(self) -> List[str]:
		lst = []
		for build in self._build_config_dir.iterdir():
			if build.suffix != '.json':
				continue
			lst.append(build.with_suffix('').name)
		return lst

	def remove_build(self, buildname: str):
		if not self.build_exists(buildname):
			return
		buildpath = self._get_build_config_path(buildname)
		assert buildpath.exists()
		buildpath.unlink()


	def print(self):
		print(f"ccache directory: {self.get_ccache_dir()}")
		print(f"builds directory: {self.get_builds_dir()}")


class UnknownBuildError(Exception):
	def __init__(self, name: str):
		super().__init__(f"unknown build name '{name}'")


class Build:

	_config: Config = None
	_name: str = None
	_vendor: str = None
	_release: str = None
	_sources: str = None

	def __init__(self, config: Config, name: str):
		self._config = config
		self._name = name
		self._read_config()

	def _read_config(self):
		if not config.build_exists(self._name):
			raise UnknownBuildError(self._name)
		build_config = self._config.get_build_config(self._name)
		assert build_config is not None
		assert 'name' in build_config
		assert 'vendor' in build_config
		assert 'release' in build_config
		assert 'sources' in build_config
		assert self._name == build_config['name']
		self._vendor = build_config['vendor']
		self._release = build_config['release']
		self._sources = build_config['sources']

	@classmethod
	def create(cls, config, name, vendor, release, sources):
		conf_dict = {
			'name': name,
			'vendor': vendor,
			'release': release,
			'sources': sources
		}
		config.write_build_config(name, conf_dict)
		return Build(config, name)

	def get_build_dir(self) -> str:
		builds = self._config.get_builds_dir()
		return str(builds.joinpath(self._name))

	def get_sources_dir(self) -> str:
		return self._sources

	def print(self, with_prefix=False, verbose=False):
		lst = [
			("- ", "buildname:", self._name),
			("   - ", "vendor:", self._vendor),
			("   - ", "release:", self._release),
			("   - ", "sourcedir:", self._sources),
			("   - ", "build dir:", self.get_build_dir())
		]
		for p, k, v in lst:
			s = "{}{}".format((p if with_prefix else ""), k)			
			print("{} {}".format(click.style(s, fg="cyan"), v))
			if not verbose:
				break

	def _remove_build(self):
		builds_dir = config.get_builds_dir()
		buildpath = builds_dir.joinpath(self._name)
		if not buildpath.exists() or not buildpath.is_dir():
			return
		buildpath.rmdir()

	def _remove_containers(self):		
		pass

	def _destroy(self, remove_build=False, remove_containers=False):
		if remove_build:
			self._remove_build()
		if remove_containers:
			self._remove_containers()
		config.remove_build(self._name)

	@classmethod
	def destroy(cls, config: Config, name: str,
	            remove_build=False,
	            remove_containers=False):
		build = Build(config, name)
		build._destroy(remove_build, remove_containers)


	def _build(self):
		cfg = self._config.get_config_path()
		cmd = "buildah unshare ./build.sh {} {} {} -c {} --buildname {}".format(
			self._vendor, self._release, self._sources, cfg, self._name
		)
		proc = subprocess.run(shlex.split(cmd), stdout=sys.stdout)
		if proc.returncode != 0:
			click.secho(f"error building: {proc.returncode}", fg="red")
		else:
			click.secho(f"succesfully built", fg="green")

	@classmethod
	def build(cls, config: Config, name: str, nuke_build=False):
		if not config.build_exists(name):
			raise UnknownBuildError(name)
		build = Build(config, name)

		# nuke an existing build directory; force rebuild from start.    
		if nuke_build:
			sources_dir: str = build.get_sources_dir()
			sources_path: Path = Path(sources_dir)
			assert sources_path.exists() and sources_path.is_dir()
			bin_build_path = sources_path.joinpath('build')
			if bin_build_path.exists():
				assert bin_build_path.is_dir()
				shutil.rmtree(bin_build_path)
	
		build._build()


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
		

config = Config()


@click.group()
def cli():
	# print(f"config path: {config._config_dir}")
	# print(f"has config? {config.has_config()}")
	pass


def _prompt_directory(prompt_text: str) -> str:
	path = None
	while True:
		pathstr = click.prompt(
			click.style(prompt_text, fg="cyan"),
			type=str, default=None)
		path = Path(pathstr).absolute()
		if not path.exists() or not path.is_dir():
			click.secho("error: path does not exist or is not a directory.",
			            fg="red")
			continue
		break
	return str(path)


@click.command()
def init():
	"""Initiate the required configuration to perform builds."""

	if config.has_config() and \
	   not click.confirm(
		   click.style("Configuration file already exists. Continue?",
		   			   fg="red")):
		return

	config_path = config.get_config_path()
	
	while True:
		builds_dir = _prompt_directory("builds directory")			
		if click.confirm(
			click.style("Use ccache to speed up builds?", fg="green"),
			default=True):
			ccache_dir = _prompt_directory("ccache directory")			

		tlen = max(len(builds_dir), len(ccache_dir), len(config_path))+18
		t = "-"*tlen
		print(t)
		print(
f"""
     config path: {config_path}
builds directory: {builds_dir}
ccache directory: {ccache_dir}
""")
		print(t)
		if click.confirm(
			click.style("Is this okay?", fg="green"),
			default=True):
			break

	config.set_ccache_dir(ccache_dir)
	config.set_builds_dir(builds_dir)
	config.commit()
	print("configuration saved.")



@click.command()
@click.argument('buildname', type=click.STRING)
@click.argument('vendor', type=click.STRING)
@click.argument('release', type=click.STRING)
@click.argument('sourcedir',
	type=click.Path(exists=True, file_okay=False,
	                writable=True, resolve_path=True))
def create(buildname: str, vendor: str, release: str, sourcedir: str):
	"""Create a new build; does not build.

	BUILDNAME is the name for the build.\n
	VENDOR is the vendor to be used for this build.\n
	RELEASE is the release to be used for this build.\n
	SOURCEDIR is the directory where sources for this build are expected.\n
	"""
	if config.build_exists(buildname):
		click.secho(f"build '{buildname}' already exists.", fg="red")
		sys.exit(errno.EEXIST)

	# check whether a build image for <vendor>:<release> exists

	img, img_id = Containers.find_release_base_image(vendor, release)
	if not img or not img_id:
		click.secho(
			f"error: unable to find base image for vendor {vendor}" \
			f" release {release}",
			fg="red")
		click.secho("please run image-build.sh")
		sys.exit(errno.ENOENT)

	# check whether sourcedir is a ceph repository
	sourcepath: Path = Path(sourcedir).resolve()
	if not sourcepath.exists() or not sourcepath.is_dir():
		click.secho(
			f"error: sourcedir expected to exist as a directory",
		    fg="red")
		sys.exit(errno.ENOTDIR)
	
	specfile = sourcepath.joinpath('ceph.spec.in')
	if not specfile.exists():
		click.secho(
			f"error: sourcedir is not a ceph git source tree",
			fg="red"
		)
		sys.exit(errno.EINVAL)
	
	build = Build.create(config, buildname, vendor, release, sourcedir)
	build.print()
	click.secho(f"created build '{buildname}'", fg="green")



@click.command()
@click.argument('buildname', type=click.STRING)
@click.option('--nuke-build', default=False, is_flag=True)
def build(buildname: str, nuke_build: bool):
	"""Starts a new build.

	Will run a new build for the sources specified by BUILDNAME, and will create
	an image, either original or incremental.

	BUILDNAME is the name of the build being built.
	"""
	if not config.build_exists(buildname):
		click.secho(f"error: build '{buildname}' does not exist.", fg="red")
		sys.exit(errno.ENOENT)

	Build.build(config, buildname, nuke_build=nuke_build)


@click.command()
@click.argument('buildname', type=click.STRING)
def destroy(buildname: str):
	"""Destroy an existing build.

	Will always remove the existing configuration for build BUILDNAME.
	Optionally, may also remove existing an existing build, and the build's
	containers.

	BUILDNAME is the name of the build to be destroyed.
	"""

	if not config.build_exists(buildname):
		click.secho(f"build '{buildname}' does not exist")
		sys.exit(errno.ENOENT)

	if not click.confirm(f"Are you sure you want to remove build '{buildname}?",
	                     default=False):
		sys.exit(0)

	remove_build = click.confirm(f"Do you want to remove the build directory?",
	                             default=False)
	remove_containers = click.confirm(f"Do you want to remove the containers?",
	                                  default=False)
	Build.destroy(config, buildname,
	              remove_build=remove_build,
	              remove_containers=remove_containers)
	print(f"destroyed build '{buildname}'")
	


@click.command()
@click.option('-v', '--verbose', default=False, is_flag=True)
def list_builds(verbose: bool):
	build_names: List[str] = config.get_builds()
	for buildname in build_names:
		build = Build(config, buildname)
		build.print(with_prefix=True, verbose=True)


@click.command()
@click.argument('buildname', type=click.STRING)
def list_build_images(buildname: str):
	if not config.build_exists(buildname):
		click.secho(f"build '{buildname}' does not exist.", fg="red")
		sys.exit(errno.ENOENT)
	
	images: List[ContainerImage] = Containers.find_build_images(name=buildname)
	if len(images) == 0:
		click.secho(f"no images for build '{buildname}'", fg="red")
		sys.exit(0)
	
	img: ContainerImage
	for img in images:
		img.print()


@click.command()
@click.argument('buildname', type=click.STRING)
def shell(buildname: str):
	"""Drop into shell of build's latest container.

	BUILDNAME is the name of the build for which we want a shell.
	"""
	if not config.build_exists(buildname):
		click.secho(f"build '{buildname}' does not exist.", fg="red")
		sys.exit(errno.ENOENT)

	if not Containers.run_shell(buildname):
		click.secho(f"unable to run shell for build '{buildname}'", fg="red")
		sys.exit(errno.EINVAL)


cli.add_command(init)
cli.add_command(create)
cli.add_command(build)
cli.add_command(destroy)
cli.add_command(list_builds)
cli.add_command(list_build_images)
cli.add_command(shell)


if __name__ == '__main__':
	cli()