#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct BeidouImgDirectory BeidouImgDirectory;

typedef enum BeidouImgNodeType {
    BEIDOU_IMG_NODE_NONE = 0,
    BEIDOU_IMG_NODE_INTEGER = 1,
    BEIDOU_IMG_NODE_REAL = 2,
    BEIDOU_IMG_NODE_STRING = 3,
    BEIDOU_IMG_NODE_VECTOR = 4,
    BEIDOU_IMG_NODE_BITMAP = 5,
    BEIDOU_IMG_NODE_AUDIO = 6,
    BEIDOU_IMG_NODE_UOL = 7
} BeidouImgNodeType;

typedef struct BeidouImgNodeInfo {
    uint32_t name_string_id;
    uint32_t children;
    uint32_t value_string_id;
    uint32_t source_file_id;
    uint32_t source_order;
    uint32_t bitmap_id;
    uint32_t audio_id;
    uint32_t audio_length;
    uint16_t child_count;
    uint16_t type;
    uint16_t bitmap_width;
    uint16_t bitmap_height;
    int64_t integer;
    double real;
    int32_t vector_x;
    int32_t vector_y;
} BeidouImgNodeInfo;

int beidou_img_directory_open(const char* path, int base_only, BeidouImgDirectory** result,
                              char* error, size_t error_capacity);
// Open exactly one IMG. Node zero is the image root; close/enumerate it with
// the directory functions below. No sibling files or directories are read.
int beidou_img_file_open(const char* path, BeidouImgDirectory** result,
                         char* error, size_t error_capacity);
void beidou_img_directory_close(BeidouImgDirectory* directory);
size_t beidou_img_directory_node_count(const BeidouImgDirectory* directory);
size_t beidou_img_directory_string_count(const BeidouImgDirectory* directory);
size_t beidou_img_directory_source_count(const BeidouImgDirectory* directory);
int beidou_img_directory_node(const BeidouImgDirectory* directory, size_t index,
                              BeidouImgNodeInfo* result);
const char* beidou_img_directory_string(const BeidouImgDirectory* directory, size_t index,
                                        size_t* length);
const char* beidou_img_directory_source(const BeidouImgDirectory* directory, size_t index,
                                        size_t* length);

#ifdef __cplusplus
}
#endif
