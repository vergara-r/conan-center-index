from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.apple import fix_apple_shared_install_name
from conan.tools.env import VirtualBuildEnv, VirtualRunEnv
from conan.tools.files import chdir, copy, get, rename, rm, rmdir, export_conandata_patches, apply_conandata_patches
from conan.tools.gnu import PkgConfigDeps
from conan.tools.layout import basic_layout
from conan.tools.meson import Meson, MesonToolchain
from conan.tools.microsoft import is_msvc, check_min_vs

import glob
import os

required_conan_version = ">=1.60.0 <2 || >=2.0.5"

class GStreamerConan(ConanFile):
    name = "gstreamer"
    description = "GStreamer is a development framework for creating applications like media players, video editors, streaming media broadcasters and so on"
    topics = ("multimedia", "video", "audio", "broadcasting", "framework", "media")
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://gstreamer.freedesktop.org/"
    license = "LGPL-2.0-or-later"
    package_type = "library"
    settings = "os", "arch", "compiler", "build_type"
    options = {
        "shared": [True, False],
        "fPIC": [True, False],
        "with_introspection": [True, False],
        "qt": [5, 6, None],
    }
    default_options = {
        "shared": True,
        "fPIC": True,
        "with_introspection": False,
        "qt": 6,
    }

    @property
    def _settings_build(self):
        return getattr(self, "settings_build", self.settings)

    @property
    def _is_legacy_one_profile(self):
        return not hasattr(self, "settings_build")

    def export_sources(self):
        export_conandata_patches(self)

    def config_options(self):
        if self.settings.os == 'Windows':
            del self.options.fPIC

    def configure(self):
        if self.options.shared:
            self.options.rm_safe("fPIC")
        self.settings.rm_safe("compiler.libcxx")
        self.settings.rm_safe("compiler.cppstd")

    def layout(self):
        basic_layout(self, src_folder="src")

    def requirements(self):
        if (self.version == "1.18.4"):
            self.requires("glib/2.66.8", transitive_headers=True, transitive_libs=True)
        else:
            self.requires("glib/2.76.3", transitive_headers=True, transitive_libs=True)
        if (self.options.qt != None):
            # Needed for windows build
            self.requires("libpng/1.6.43")

    def validate(self):
        if self.settings.os != 'Linux' and not self.dependencies.direct_host["glib"].options.shared and self.options.shared:
            # https://gitlab.freedesktop.org/gstreamer/gst-build/-/issues/133
            raise ConanInvalidConfiguration("shared GStreamer cannot link to static GLib")

    def build_requirements(self):
        self.tool_requires("meson/1.3.0")
        # There used to be an issue with glib being shared by default but its dependencies being static
        # No longer the case, but see: https://github.com/conan-io/conan-center-index/pull/13400#issuecomment-1551565573 for context
        if not self._is_legacy_one_profile:
            self.tool_requires("glib/<host_version>")
        if not self.conf.get("tools.gnu:pkg_config", check_type=str):
            self.tool_requires("pkgconf/2.1.0")
        if self.options.with_introspection:
            self.tool_requires("gobject-introspection/1.72.0")
        if self.settings_build.get_safe('os') == 'Windows':
            self.tool_requires("winflexbison/2.5.24")
        else:
            self.tool_requires("bison/3.8.2")
            self.tool_requires("flex/2.6.4")
        if (self.options.qt != None):
            self.tool_requires("opengl/system")
            self.tool_requires("opengl-registry/cci.20220929")
            if (self.options.qt == 6):
                self.tool_requires("qt/6.6.2")
            elif (self.options.qt == 5):
                self.tool_requires("qt/5.15.11")

    def source(self):
        get(self, **self.conan_data["sources"][self.version], strip_root=True)

    def generate(self):
        virtual_build_env = VirtualBuildEnv(self)
        virtual_build_env.generate()
        if self._is_legacy_one_profile:
            VirtualRunEnv(self).generate(scope="build")
        pkg_config_deps = PkgConfigDeps(self)
        pkg_config_deps.generate()
        tc = MesonToolchain(self)
        if is_msvc(self) and not check_min_vs(self, "190", raise_invalid=False):
            tc.project_options["c_std"] = "c99"
        tc.project_options["tools"] = "enabled"
        tc.project_options["examples"] = "disabled"
        if (self.version < "1.22.0"):
            tc.project_options["benchmarks"] = "disabled"
        subproj_opt = ""
        if (self.options.qt != None):
            # ninja backend generates "gstreamer-full-1.0.dll.rsp : fatal error LNK1170: line in command file contains 131071 or more characters"
            # needs "in_newline" option
            #tc._backend = "vs2022"
            if self.settings.os == "Windows":
                #tc.project_options["tools"] = "disabled"
                subproj_opt = "\n[gst-plugins-base:built-in options]\nrawparse = 'enabled'\ngl = 'enabled'\ngl_winsys = 'win32'\ngl_platform = 'wgl'\n"
                if (self.options.qt == 6):
                    subproj_opt += "[gst-plugins-good:built-in options]\nqt6 = 'enabled'\npng = 'enabled'\n"
            else:
                qt_dir = self.dependencies.direct_build["qt"].package_folder
                qt_dir += "/../b/build/Release"
                tc.pkg_config_path = f"{tc.pkg_config_path}:{qt_dir}/generators:{qt_dir}/qtbase/lib/pkgconfig"
                subproj_opt = "[gst-plugins-base:built-in options]\nrawparse = 'enabled'\ngl = 'enabled'\n"
                if (self.options.qt == 6):
                    subproj_opt += "[gst-plugins-good:built-in options]\nqt6 = 'enabled'\nv4l2 = 'enabled'\npng = 'enabled'\n"
            tc._meson_file_template = f"{tc._meson_file_template}{subproj_opt}"

            if (self.version >= "1.19.0"):
                tc.project_options["bad"] = "disabled"
                tc.project_options["ugly"] = "disabled"
            if (self.options.qt == 5):
                tc.project_options["qt5"] = "enabled"

        tc.project_options["tests"] = "disabled"
        tc.project_options["introspection"] = "enabled" if self.options.with_introspection else "disabled"
        tc.generate()

    def _patch_sources(self):
        apply_conandata_patches(self)

    def build(self):
        self._patch_sources()
        meson = Meson(self)
        meson.configure()
        meson.build()

    def _fix_library_names(self, path):
        # regression in 1.16
        if is_msvc(self):
            with chdir(self, path):
                for filename_old in glob.glob("*.a"):
                    filename_new = filename_old[3:-2] + ".lib"
                    self.output.info(f"rename {filename_old} into {filename_new}")
                    if (os.path.exists(filename_new)):
                        rm(self, filename_new, path, False)
                    rename(self, filename_old, filename_new)

    def package(self):
        copy(self, "COPYING", self.source_folder, os.path.join(self.package_folder, "licenses"))
        meson = Meson(self)
        meson.install()

        self._fix_library_names(os.path.join(self.package_folder, "lib"))
        self._fix_library_names(os.path.join(self.package_folder, "lib", "gstreamer-1.0"))
        rmdir(self, os.path.join(self.package_folder, "lib", "pkgconfig"))
        rmdir(self, os.path.join(self.package_folder, "lib", "gstreamer-1.0", "pkgconfig"))
        rmdir(self, os.path.join(self.package_folder, "share"))
        rm(self, "*.pdb", self.package_folder, recursive=True)
        fix_apple_shared_install_name(self)

    def package_info(self):
        gst_plugin_path = os.path.join(self.package_folder, "lib", "gstreamer-1.0")

        pkgconfig_variables = {
            "exec_prefix": "${prefix}",
            "toolsdir": "${exec_prefix}/bin",
            # PkgConfigDep uses libdir1 instead of libdir, so the path is spelled out explicitly here.
            "pluginsdir": "${prefix}/lib/gstreamer-1.0",
            "datarootdir": "${prefix}/share",
            "datadir": "${datarootdir}",
            "girdir": "${datadir}/gir-1.0",
            "typelibdir": "${prefix}/lib/girepository-1.0",
            "libexecdir": "${prefix}/libexec",
            "pluginscannerdir": "${libexecdir}/gstreamer-1.0",
        }
        pkgconfig_custom_content = "\n".join("{}={}".format(key, value) for key, value in pkgconfig_variables.items())

        self.cpp_info.components["gstreamer-1.0"].set_property("pkg_config_name", "gstreamer-1.0")
        self.cpp_info.components["gstreamer-1.0"].names["pkg_config"] = "gstreamer-1.0"
        self.cpp_info.components["gstreamer-1.0"].requires = ["glib::glib-2.0", "glib::gobject-2.0"]
        if not self.options.shared:
            self.cpp_info.components["gstreamer-1.0"].requires.append("glib::gmodule-no-export-2.0")
            self.cpp_info.components["gstreamer-1.0"].defines.append("GST_STATIC_COMPILATION")
        self.cpp_info.components["gstreamer-1.0"].libs = ["gstreamer-1.0"]
        self.cpp_info.components["gstreamer-1.0"].includedirs = [os.path.join("include", "gstreamer-1.0")]
        if self.settings.os == "Linux":
            self.cpp_info.components["gstreamer-1.0"].system_libs = ["m"]
        self.cpp_info.components["gstreamer-1.0"].set_property("pkg_config_custom_content", pkgconfig_custom_content)

        self.cpp_info.components["gstreamer-base-1.0"].set_property("pkg_config_name", "gstreamer-base-1.0")
        self.cpp_info.components["gstreamer-base-1.0"].names["pkg_config"] = "gstreamer-base-1.0"
        self.cpp_info.components["gstreamer-base-1.0"].requires = ["gstreamer-1.0"]
        self.cpp_info.components["gstreamer-base-1.0"].libs = ["gstbase-1.0"]
        self.cpp_info.components["gstreamer-base-1.0"].includedirs = [os.path.join("include", "gstreamer-1.0")]
        self.cpp_info.components["gstreamer-base-1.0"].set_property("pkg_config_custom_content", pkgconfig_custom_content)

        self.cpp_info.components["gstreamer-controller-1.0"].set_property("pkg_config_name", "gstreamer-controller-1.0")
        self.cpp_info.components["gstreamer-controller-1.0"].names["pkg_config"] = "gstreamer-controller-1.0"
        self.cpp_info.components["gstreamer-controller-1.0"].requires = ["gstreamer-1.0"]
        self.cpp_info.components["gstreamer-controller-1.0"].libs = ["gstcontroller-1.0"]
        self.cpp_info.components["gstreamer-controller-1.0"].includedirs = [os.path.join("include", "gstreamer-1.0")]
        if self.settings.os == "Linux":
            self.cpp_info.components["gstreamer-controller-1.0"].system_libs = ["m"]
        self.cpp_info.components["gstreamer-controller-1.0"].set_property("pkg_config_custom_content", pkgconfig_custom_content)

        self.cpp_info.components["gstreamer-net-1.0"].set_property("pkg_config_name", "gstreamer-net-1.0")
        self.cpp_info.components["gstreamer-net-1.0"].names["pkg_config"] = "gstreamer-net-1.0"
        self.cpp_info.components["gstreamer-net-1.0"].requires = ["gstreamer-1.0", "glib::gio-2.0"]
        self.cpp_info.components["gstreamer-net-1.0"].libs = ["gstnet-1.0"]
        self.cpp_info.components["gstreamer-net-1.0"].includedirs = [os.path.join("include", "gstreamer-1.0")]
        self.cpp_info.components["gstreamer-net-1.0"].set_property("pkg_config_custom_content", pkgconfig_custom_content)

        self.cpp_info.components["gstreamer-check-1.0"].set_property("pkg_config_name", "gstreamer-check-1.0")
        self.cpp_info.components["gstreamer-check-1.0"].names["pkg_config"] = "gstreamer-check-1.0"
        self.cpp_info.components["gstreamer-check-1.0"].requires = ["gstreamer-1.0"]
        self.cpp_info.components["gstreamer-check-1.0"].libs = ["gstcheck-1.0"]
        self.cpp_info.components["gstreamer-check-1.0"].includedirs = [os.path.join("include", "gstreamer-1.0")]
        if self.settings.os == "Linux":
            self.cpp_info.components["gstreamer-check-1.0"].system_libs = ["rt", "m"]
        self.cpp_info.components["gstreamer-check-1.0"].set_property("pkg_config_custom_content", pkgconfig_custom_content)

        if (self.options.qt != None):
            self.cpp_info.components["gstreamer-video-1.0"].set_property("pkg_config_name", "gstreamer-video-1.0")
            self.cpp_info.components["gstreamer-video-1.0"].names["pkg_config"] = "gstreamer-video-1.0"
            self.cpp_info.components["gstreamer-video-1.0"].requires = ["gstreamer-1.0"]
            self.cpp_info.components["gstreamer-video-1.0"].libs = ["gstvideo-1.0"]
            self.cpp_info.components["gstreamer-video-1.0"].includedirs = [os.path.join("include", "gstreamer-1.0")]
            self.cpp_info.components["gstreamer-video-1.0"].set_property("pkg_config_custom_content", pkgconfig_custom_content)

            self.cpp_info.components["gstreamer-gl-1.0"].set_property("pkg_config_name", "gstreamer-gl-1.0")
            self.cpp_info.components["gstreamer-gl-1.0"].names["pkg_config"] = "gstreamer-gl-1.0"
            self.cpp_info.components["gstreamer-gl-1.0"].requires = ["gstreamer-1.0", "libpng::libpng"]
            self.cpp_info.components["gstreamer-gl-1.0"].libs = ["gstgl-1.0"]
            self.cpp_info.components["gstreamer-gl-1.0"].includedirs = [os.path.join("include", "gstreamer-1.0")]
            self.cpp_info.components["gstreamer-gl-1.0"].set_property("pkg_config_custom_content", pkgconfig_custom_content)

        # gstcoreelements and gstcoretracers are plugins which should be loaded dynamicaly, and not linked to directly
        if not self.options.shared:
            self.cpp_info.components["gstcoreelements"].set_property("pkg_config_name", "gstcoreelements")
            self.cpp_info.components["gstcoreelements"].names["pkg_config"] = "gstcoreelements"
            self.cpp_info.components["gstcoreelements"].requires = ["glib::gobject-2.0", "glib::glib-2.0", "gstreamer-1.0", "gstreamer-base-1.0"]
            self.cpp_info.components["gstcoreelements"].libs = ["gstcoreelements"]
            self.cpp_info.components["gstcoreelements"].includedirs = [os.path.join("include", "gstreamer-1.0")]
            self.cpp_info.components["gstcoreelements"].libdirs = [gst_plugin_path]

            self.cpp_info.components["gstcoretracers"].set_property("pkg_config_name", "gstcoretracers")
            self.cpp_info.components["gstcoretracers"].names["pkg_config"] = "gstcoretracers"
            self.cpp_info.components["gstcoretracers"].requires = ["gstreamer-1.0"]
            self.cpp_info.components["gstcoretracers"].libs = ["gstcoretracers"]
            self.cpp_info.components["gstcoretracers"].includedirs = [os.path.join("include", "gstreamer-1.0")]
            self.cpp_info.components["gstcoretracers"].libdirs = [gst_plugin_path]

        if self.options.shared:
            self.runenv_info.define_path("GST_PLUGIN_PATH", gst_plugin_path)
        gstreamer_root = self.package_folder
        gst_plugin_scanner = "gst-plugin-scanner.exe" if self.settings.os == "Windows" else "gst-plugin-scanner"
        gst_plugin_scanner = os.path.join(self.package_folder, "bin", "gstreamer-1.0", gst_plugin_scanner)
        self.runenv_info.define_path("GSTREAMER_ROOT", gstreamer_root)
        self.runenv_info.define_path("GST_PLUGIN_SCANNER", gst_plugin_scanner)
        if self.settings.arch == "x86":
            self.runenv_info.define_path("GSTREAMER_ROOT_X86", gstreamer_root)
        elif self.settings.arch == "x86_64":
            self.runenv_info.define_path("GSTREAMER_ROOT_X86_64", gstreamer_root)

        # TODO: remove the following when only Conan 2.0 is supported
        if self.options.shared:
            self.env_info.GST_PLUGIN_PATH.append(gst_plugin_path)
        self.env_info.GSTREAMER_ROOT = gstreamer_root
        self.env_info.GST_PLUGIN_SCANNER = gst_plugin_scanner
        if self.settings.arch == "x86":
            self.env_info.GSTREAMER_ROOT_X86 = gstreamer_root
        elif self.settings.arch == "x86_64":
            self.env_info.GSTREAMER_ROOT_X86_64 = gstreamer_root
