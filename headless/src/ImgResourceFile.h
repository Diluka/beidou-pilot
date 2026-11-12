#pragma once

#include <filesystem>
#include <nlnx/file.hpp>

nl::file load_img_directory(std::filesystem::path const& path, bool base_only = false);
