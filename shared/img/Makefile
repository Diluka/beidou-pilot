CXX ?= g++
CXXFLAGS ?= -std=c++17 -O2 -fPIC

BUILD := build
OBJECTS := $(BUILD)/ImgResources.o $(BUILD)/ImgKeys.o

.PHONY: all clean
all: $(BUILD)/libbeidou-img.so

$(BUILD)/libbeidou-img.so: $(OBJECTS)
	$(CXX) -shared -o $@ $^

$(BUILD)/%.o: %.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@

clean:
	rm -rf $(BUILD)

-include $(OBJECTS:.o=.d)
