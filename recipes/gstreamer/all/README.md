# With ninja backend
conan create --version 1.22.6 -vvv -o shared=True --update --build=missing -pr:h default-x86_64-windows-msvc193-cppstd17 -pr:b default-x86_64-windows-msvc193-cppstd14  conanfile.py
