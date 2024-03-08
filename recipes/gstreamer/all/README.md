# Conan package for MSVC -> vc2022 backend is needed, due to:
# ninja backend generates "gstreamer-full-1.0.dll.rsp : fatal error LNK1170: line in command file contains 131071 or more characters"
# needs "in_newline" option (see https://ninja-build.org/manual.html  #in_newline)
conan create --version 1.22.6 -vvv -o qt=6 --update --build=missing -pr:h default-x86_64-windows-msvc193-cppstd17 -pr:b default-x86_64-windows-msvc193-cppstd17 -pr:h vs_profile  conanfile.py