CXX ?= g++
AR ?= ar
CC ?= gcc
RUNTIME_ROOT ?= ../shared/lua-runtime
LUA_ROOT ?= ../third_party/lua
LUA_SOURCES := $(filter-out $(LUA_ROOT)/lua.c $(LUA_ROOT)/luac.c $(LUA_ROOT)/ltests.c $(LUA_ROOT)/onelua.c,$(wildcard $(LUA_ROOT)/*.c))
LUA_OBJECTS := $(patsubst $(LUA_ROOT)/%.c,build/lua/%.o,$(LUA_SOURCES))
ENGINE := ../third_party/maplestory-client
NX := $(ENGINE)/includes/NoLifeNx/nlnx
CPPFLAGS := -DHEADLESS -DGLFW_INCLUDE_NONE -I$(ENGINE) -I$(ENGINE)/includes/NoLifeNx -I$(ENGINE)/includes/glfw-3.3.2.bin.WIN64/include/GLFW -I$(NX)/includes/lz4_v1_8_2_win32/include -I$(RUNTIME_ROOT) -I$(LUA_ROOT) -I../third_party/json/single_include -Isrc -include src/PlatformIncludes.h
CXXFLAGS ?= -std=c++20 -O0 -g1 -ffunction-sections -fdata-sections
LDFLAGS ?= -Wl,--gc-sections
LDLIBS := -pthread -l:liblz4.so.1
ENGINE_SOURCES := $(shell find $(ENGINE)/Audio $(ENGINE)/Character $(ENGINE)/Data $(ENGINE)/Gameplay $(ENGINE)/Graphics $(ENGINE)/IO $(ENGINE)/Net $(ENGINE)/Util -name '*.cpp' ! -name SocketWinsock.cpp) $(ENGINE)/Configuration.cpp $(wildcard $(NX)/*.cpp)
SOURCES := $(wildcard src/*.cpp)
OBJECTS := $(patsubst $(ENGINE)/%.cpp,build/engine/%.o,$(ENGINE_SOURCES)) $(patsubst %.cpp,build/%.o,$(SOURCES)) build/shared/Runtime.o build/shared/TaskTransport.o $(LUA_OBJECTS)
DEPS := $(OBJECTS:.o=.d)

.PHONY: all objects clean
all: build/beidou-headless
objects: $(OBJECTS)
build/beidou-headless: $(OBJECTS)
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS)
build/engine/%.o: $(ENGINE)/%.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/%.o: %.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/shared/%.o: $(RUNTIME_ROOT)/%.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -I$(LUA_ROOT) -MMD -MP -c $< -o $@
build/lua/%.o: $(LUA_ROOT)/%.c
	@mkdir -p $(dir $@)
	$(CC) -O2 -ffunction-sections -fdata-sections -MMD -MP -c $< -o $@
clean:
	rm -rf build/engine build/src build/shared build/lua build/beidou-headless
-include $(DEPS)
