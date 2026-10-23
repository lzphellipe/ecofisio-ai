set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Núcleo C++ puro, sem dependência de Python: é o que os testes C++ e o binding usam.
add_library(ecofisio_core STATIC src/fvcb.cpp)
target_include_directories(ecofisio_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
set_target_properties(ecofisio_core PROPERTIES POSITION_INDEPENDENT_CODE ON)
if(MSVC)
  target_compile_options(ecofisio_core PRIVATE /W4)
else()
  target_compile_options(ecofisio_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(ECOFISIO_BUILD_PYTHON)
  find_package(Python 3.11 COMPONENTS Interpreter Development.Module REQUIRED)
  execute_process(
    COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
    OUTPUT_STRIP_TRAILING_WHITESPACE
    OUTPUT_VARIABLE nanobind_ROOT)
  find_package(nanobind CONFIG REQUIRED)

  nanobind_add_module(_kernels NB_STATIC bindings/module.cpp)
  target_link_libraries(_kernels PRIVATE ecofisio_core)
  install(TARGETS _kernels LIBRARY DESTINATION ecofisio)
endif()

if(ECOFISIO_BUILD_CPP_TESTS)
  # Usa o GoogleTest instalado no sistema; se não houver, baixa a versão fixada via git.
  find_package(GTest 1.14 QUIET)
  if(NOT GTest_FOUND)
    include(FetchContent)
    FetchContent_Declare(
      googletest
      GIT_REPOSITORY https://github.com/google/googletest.git
      GIT_TAG v1.15.2
      GIT_SHALLOW TRUE)
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
  endif()

  add_executable(test_fvcb tests/test_fvcb.cpp)
  target_link_libraries(test_fvcb PRIVATE ecofisio_core GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(test_fvcb)
endif()
