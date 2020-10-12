import click
import sys
import shlex
import subprocess
import shutil
import os
from pathlib import Path
from datetime import datetime as dt
from typing import Tuple, List, Optional
from .config import Config, UnknownBuildError
from .utils import print_tree, print_table, pwarn, pinfo, pokay, perror
from .buildah import Buildah
from .container_image import ContainerImage, ContainerImageName
from .images import Images


def cprint(prefix: str, suffix: str):
    print("{}: {}".format(click.style(prefix, fg="cyan"), suffix))


class NoAvailableImageError(Exception):
    pass


class BuildError(Exception):
    pass


class ContainerBuildError(Exception):
    pass


def raise_build_error(retcode: int, msg=None):
    err_msg = f"error: {os.strerror(retcode)}"
    if msg:
        err_msg += f": {msg}"
    raise ContainerBuildError(err_msg)


class Build:

    _config: Config
    _name: str
    _vendor: Optional[str] = None
    _release: Optional[str] = None
    _sources: Optional[str] = None

    _with_debug: bool = False
    _with_tests: bool = False

    def __init__(self, config: Config, name: str):
        self._config = config
        self._name = name
        self._read_config()

    def _read_config(self):
        if not self._config.build_exists(self._name):
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

        if 'build' in build_config:
            if 'debug' in build_config['build']:
                self._with_debug = build_config['build']['debug']
            if 'tests' in build_config['build']:
                self._with_tests = build_config['build']['tests']

    @classmethod
    def create(cls, config, name, vendor, release, sources,
               with_debug=False, with_tests=False):
        conf_dict = {
            'name': name,
            'vendor': vendor,
            'release': release,
            'sources': sources,
            'build': {
                'debug': with_debug,
                'tests': with_tests
            }
        }
        config.write_build_config(name, conf_dict)
        return Build(config, name)

    @property
    def with_debug(self):
        return self._with_debug

    @property
    def with_tests(self):
        return self._with_tests

    def get_install_path(self) -> Path:
        installs = self._config.get_installs_dir()
        return installs.joinpath(self._name)

    def get_install_dir(self) -> str:
        return str(self.get_install_path())

    def get_sources_dir(self) -> Optional[str]:
        return self._sources

    def print(self, with_prefix=False, verbose=False):
        tree = [
            ('buildname', self._name, [
                ('vendor', self._vendor),
                ('release', self._release),
                ('sources', self._sources),
                ('install', self.get_install_dir()),
                ('build', '', [
                    ('with debug', self.with_debug),
                    ('with tests', self.with_tests)
                ])
            ])
        ]
        print_tree(tree)

    def _remove_install(self) -> bool:
        installpath = self.get_install_path()
        if not installpath.exists() or not installpath.is_dir():
            click.secho("  - build path not found", fg="green")
            return True
        try:
            shutil.rmtree(installpath)
        except Exception as e:
            click.secho(f"error removing install directory: {str(e)}")
            return False
        return True

    def _remove_containers(self) -> bool:
        imgs: List[ContainerImage] = Images.find_build_images(self._name)
        imgs = sorted(imgs, key=lambda img: img._created, reverse=True)
        for img in imgs:
            if not Images.rm_image(img):
                return False
        return True

    def _destroy(self, remove_install=False, remove_containers=False) -> bool:

        success = True
        while True:
            if remove_install:
                installpath = self.get_install_path()
                pwarn(f"=> remove install directory at {installpath}")
                if not self._remove_install():
                    success = False
                    break

            if remove_containers:
                pwarn("=> remove container images")
                if not self._remove_containers():
                    success = False
                    break
            break
        if not success:
            return False
        return self._config.remove_build(self._name)

    @classmethod
    def destroy(cls, config: Config, name: str,
                remove_install=False,
                remove_containers=False) -> bool:
        build = Build(config, name)
        return build._destroy(remove_install, remove_containers)

    @classmethod
    def build(cls, config: Config, name: str, nuke_install=False,
              with_fresh_build=False):
        if not config.build_exists(name):
            raise UnknownBuildError(name)
        build = Build(config, name)

        # nuke an existing build install directory; force reinstall.
        if nuke_install:
            install_path: Path = \
                config.get_installs_dir().joinpath(build._name)
            click.secho(
                f"=> removing install path at {install_path}", fg="yellow")
            if install_path.exists():
                assert install_path.is_dir()
                shutil.rmtree(install_path)

        build._build(with_fresh_build=with_fresh_build)

    def _build(self, do_build=True, do_container=True,
               with_fresh_build=False):

        ccache_path: Path = None
        install_path: Path = None

        # prepare ccache
        if self._config.has_ccache():
            ccache_path: Path = self._config.get_ccache_dir().joinpath(
                                         f"{self._vendor}/{self._release}")
            if not ccache_path.exists():
                ccache_path.mkdir(parents=True, exist_ok=True)
                ccache_size = self._config.get_ccache_size()
                cmd = f'ccache -M {ccache_size}'
                subprocess.run(
                    shlex.split(cmd),
                    env={'CCACHE_DIR': str(ccache_path)}
                )

        # prepare output build directory
        install_path = self.get_install_path()
        install_path.mkdir(exist_ok=True)

        if do_build:
            if not self._perform_build(install_path, ccache_path,
                                       with_fresh_build):
                raise BuildError()

        if do_container:
            if not self._build_container(install_path):
                raise ContainerBuildError()
            if self._config.has_registry():
                self._push_to_registry()

    def _perform_build(self, install_path: Path, ccache_path: Path,
                       with_fresh_build: bool
                       ) -> bool:
        """ Performs the actual, containerized build from specified sources.

            The build process is based on running a specific build container,
            based on a given release, against the build's sources, and finally
            installing the binaries into the build's build path.

            install_path is the location of the directory where our final build
            will live.

            ccache_path is the location for the vendor/release ccache.

            with_debug will instruct the build script to build with debug
            symbols.

            with_tests will instruct the build script to build the tests.

        """

        click.secho("==> building sources", fg="cyan")
        tbl = [
            ("vendor", self._vendor),
            ("release", self._release),
            ("sources path", self._sources),
            ("install path", install_path),
            ("ccache path", ccache_path),
            ("with debug", self._with_debug),
            ("with tests", self._with_tests)
        ]
        print_table(tbl, color="cyan")

        assert self._vendor
        assert self._release
        img: Optional[ContainerImage] = \
            Images.find_builder_image(self._vendor, self._release)
        if not img:
            raise BuildError("unable to find base build image")
        build_image = img.get_real_name(self._vendor, self._release)

        bindir = Path.cwd().joinpath("bin")
        extra_args = []

        if self.with_debug:
            extra_args.append("--with-debug")
        if self.with_tests:
            extra_args.append("--with-tests")
        if with_fresh_build:
            extra_args.append("--fresh-build")

        cmd = f"podman run -it --userns=keep-id " \
              f"-v {bindir}:/build/bin " \
              f"-v {self._sources}:/build/src " \
              f"-v {str(install_path)}:/build/out"

        if ccache_path is not None:
            cmd += f" -v {str(ccache_path)}:/build/ccache"
            extra_args.append("--with-ccache")

        # currently, the build image's entrypoint requires an argument to
        # perform a build using ccache.
        cmd += f" {build_image}"
        extra_args_str = ' '.join(extra_args)
        cmd += f" {extra_args_str}"

        # cprint("build cmd", cmd)
        # sys.exit(1)
        proc = subprocess.run(
                    shlex.split(cmd), stdout=sys.stdout, stderr=sys.stderr)
        if proc.returncode != 0:
            raise BuildError(os.strerror(proc.returncode))
        return True

    def _run_cmd(self, cmd: str) -> Tuple[int, str, str]:
        proc = subprocess.run(shlex.split(cmd),
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        stdout = proc.stdout.decode("utf-8")
        stderr = proc.stderr.decode("utf-8")
        return proc.returncode, stdout, stderr

    def _build_container(self,
                         install_path: Path
                         ) -> bool:

        click.secho("==> building container", fg="cyan")
        print_table([
            ("from build path", install_path),
            # ("based on", base_image)
        ], color="cyan")

        image_date, raw_image = self._build_raw_container_image(install_path)
        assert image_date
        assert raw_image

        self._build_final_container_image(image_date, raw_image)

        return True

    def _build_raw_container_image(self,
                                   install_path: Path
                                   ) -> Tuple[str, str]:

        """Create raw container image, where our binaries will end up at.

            Our binaries need an image without special permissions so that we
            can incrementally move them. To this image we call a "raw image",
            because it's still in its raw state, without permissions being set.

            These images are always based on previous raw images, or, in their
            absense, a release image.
        """

        assert self._vendor
        assert self._release
        base_image: Optional[str] = None
        if not Images.has_build_image(self._name, "latest-raw"):
            img: Optional[ContainerImage] = Images.find_base_image(
                self._vendor, self._release)
            if not img:
                raise NoAvailableImageError("missing release image")
            base_image = img.get_real_name(self._vendor, self._release)
        else:
            build_name = Images.get_build_name(self._name)
            base_image = f"{build_name}:latest-raw"
        assert base_image is not None
        assert len(base_image) > 0

        pinfo(f"=> creating raw image from {base_image}...")

        # create working container (this is where our binaries will end up at).
        #
        working_container: Buildah = Buildah(base_image)

        # mount our working container, so we can transfer our binaries.
        mnt_path: Path = working_container.mount()
        assert mnt_path
        assert mnt_path.is_dir()

        exclude_dirs = [
            "usr/share/ceph/mgr/dashboard/frontend/node_modules",
            "usr/share/ceph/mgr/dashboard/frontend/src"
        ]

        excludes = ' '.join([f'--exclude {x}' for x in exclude_dirs])

        # transfer binaries.
        cmd = f"rsync --info=stats --update --recursive --links --perms "\
              f"--group --owner --times {excludes} "\
              f"{str(install_path)}/ {str(mnt_path)}"
        ret, _, stderr = self._run_cmd(cmd)
        if ret != 0:
            raise_build_error(ret, stderr)

        working_container.unmount()

        image_date = dt.now().strftime("%Y%m%dT%H%M%SZ")
        container_image_name = Images.get_build_name(self._name)
        container_raw_image = f"{container_image_name}:{image_date}-raw"

        hashid: str = \
            working_container.commit(container_image_name, f"{image_date}-raw")
        assert working_container.is_committed()
        working_container.tag("latest-raw")
        pokay("=> created raw image {} ({})".format(
            container_raw_image, hashid[:12]))
        return image_date, container_raw_image

    def _build_final_container_image(self,
                                     datestr: str,
                                     raw_image: str
                                     ) -> str:
        # working_container = self._buildah_from(raw_image)
        # assert working_container and len(working_container) > 0
        working_container: Buildah = Buildah(raw_image)

        pinfo(f"=> creating final image from {raw_image}")
        mnt_path: Path = working_container.mount()
        assert mnt_path
        assert mnt_path.is_dir()

        # run post-install script
        #  if present, will set permissions, create users and directories, etc.
        post_install_path = mnt_path.joinpath('post-install.sh')
        if post_install_path.exists():
            ret, result = working_container.run("bash -x /post-install.sh")
            if ret != 0:
                raise_build_error(ret, result)
            post_install_path.unlink()

        working_container.unmount()

        container_build_image_name = Images.get_build_name(self._name)
        container_final_image = f"{container_build_image_name}:{datestr}"

        hashid: str = \
            working_container.commit(container_build_image_name, datestr)
        assert hashid and len(hashid) > 0
        assert working_container.is_committed()
        working_container.tag("latest")
        pokay("=> created container image {} ({})".format(
            container_final_image, hashid[:12]
        ))
        return container_final_image

    def _push_to_registry(self):

        latest_img: ContainerImage = \
            Images.find_build_image_latest(self._name)
        latest_name: ContainerImageName = latest_img.get_latest_image_name()
        img_name = f"{latest_name._repo}/{latest_name.name}:{latest_name.tag}"
        registry_url = self._config.get_registry()
        extra = ""
        if not self._config.is_registry_secure():
            extra = "--tls-verify=false"

        cmd = f"podman push {extra} {img_name} {registry_url}/{img_name}"
        pinfo(f"=> pushing {img_name} to {registry_url}")
        proc = subprocess.run(shlex.split(cmd),
                              stdout=sys.stdout, stderr=sys.stderr)
        if proc.returncode != 0:
            perror("error pushing to repository")
