cmake_minimum_required(VERSION 3.26)
project(ecofisio_kernels LANGUAGES CXX)

option(ECOFISIO_BUILD_PYTHON "Compila o módulo Python (_kernels) via nanobind" ON)
option(ECOFISIO_BUILD_CPP_TESTS "Compila os testes C++ com GoogleTest" OFF)

if(ECOFISIO_BUILD_CPP_TESTS)
  enable_testing()  # na raiz, para o ctest achar os testes a partir do diretório de build
endif()

add_subdirectory(kernels)
