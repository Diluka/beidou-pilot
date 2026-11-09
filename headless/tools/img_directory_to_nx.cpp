// Derived from NoLifeWzToNx; see third_party/nolifewztonx for AGPL-3.0-or-later notices.
// This target preserves gameplay metadata and does not contain renderable pixels/audio.
#define NL_METADATA_ONLY
#define NL_NO_MAIN
#include "../../third_party/nolifewztonx/NoLifeWzToNx.cpp"

struct directorytonx : nl::wztonx {
    bool base_only;
    size_t image_count = 0;

    directorytonx(sys::path source, sys::path target, bool base_only)
        : wztonx(source, true, false), base_only(base_only) {
        nxfilename = target.string();
    }

    void add_directory(nl::id_t parent, sys::path const & path) {
        std::vector<sys::path> entries;
        for (auto const & entry : sys::directory_iterator(path)) {
            if ((!base_only && entry.is_directory()) ||
                (entry.is_regular_file() && entry.path().extension() == ".img"))
                entries.push_back(entry.path());
        }
        std::sort(entries.begin(), entries.end());
        auto first = static_cast<nl::id_t>(nodes.size());
        nodes[parent].children = first;
        nodes[parent].num = static_cast<uint16_t>(entries.size());
        nodes.resize(first + entries.size());
        for (size_t index = 0; index < entries.size(); ++index) {
            auto child = first + static_cast<nl::id_t>(index);
            auto const & entry = entries[index];
            nodes[child].name = add_string(entry.filename().string());
            if (sys::is_directory(entry)) {
                add_directory(child, entry);
            } else {
                std::cerr << "IMG " << entry.string() << '\n';
                in.open(entry.string());
                img(child, static_cast<int32_t>(sys::file_size(entry)));
                ++image_count;
            }
        }
        nodes_to_sort.emplace_back(first, entries.size());
    }

    void parse_file() override {
        add_string({});
        add_directory(0, wzfilename);
        finish_parse();
    }

    void run() {
        parse_file();
        open_output();
        write_nodes();
        write_strings();
        write_audio();
        write_bitmaps();
        std::cout << "RESOURCE_META images=" << image_count << " nodes=" << nodes.size()
                  << " bitmaps=" << bitmaps.size() << " output=" << nxfilename << '\n';
        out.close();
    }
};

int main(int argc, char ** argv) {
    if (argc < 3 || argc > 4) {
        std::cerr << "Usage: img_directory_to_nx INPUT_DIRECTORY OUTPUT.nx [--base]\n";
        return 2;
    }
    if (!sys::is_directory(argv[1])) {
        std::cerr << "Input is not a directory\n";
        return 2;
    }
    if (sys::exists(argv[2])) {
        std::cerr << "Output already exists\n";
        return 2;
    }
    directorytonx converter(argv[1], argv[2], argc == 4 && std::string(argv[3]) == "--base");
    converter.run();
}
