cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(qr_ticket_kiosk)
idf_build_set_property(CXX_COMPILE_OPTIONS "-std=gnu++17;-Wno-misleading-indentation" APPEND)
