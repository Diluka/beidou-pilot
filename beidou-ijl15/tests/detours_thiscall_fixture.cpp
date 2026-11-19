// Independent x86 MSVC/Detours fixture. This does not validate any game ABI.
#include <windows.h>
#include <detours.h>
#include <cstdio>
#include <cstdint>
#include <cstring>

struct TestObject { int tag; int calls; };
using Target = int (__thiscall *)(TestObject*);
static TestObject* expected;
static int entries;
static int failures;
static int depth;
static int nestedResult;
static int outerResult;
static DWORD savedStack;

// Naked x86 targets model thiscall explicitly: ECX is this and the button
// target cleans its single 4-byte stack argument. They are not game code.
__declspec(naked) int __cdecl TestTarget() {
    __asm {
        nop
        nop
        nop
        nop
        nop
        inc dword ptr [ecx + 4]
        mov eax, [ecx]
        add eax, [ecx + 4]
        ret
    }
}
static Target original = reinterpret_cast<Target>(&TestTarget);

__declspec(noinline) int __fastcall Hook(TestObject* object, void*) {
    ++entries;
    if (object != expected) ++failures;
    if (depth == 0) {
        ++depth;
        Target entry = reinterpret_cast<Target>(&TestTarget);
        nestedResult = entry(object);
        --depth;
    }
    return original(object);
}

using ButtonTarget = int (__thiscall *)(TestObject*, int);
static int buttonEntries;
static int buttonArgument;
__declspec(naked) int __cdecl TestButton() {
    __asm {
        nop
        nop
        nop
        nop
        nop
        mov eax, [ecx]
        add eax, [esp + 4]
        ret 4
    }
}
static ButtonTarget originalButton = reinterpret_cast<ButtonTarget>(&TestButton);

__declspec(noinline) int __fastcall ButtonHook(TestObject* object, void*, int control) {
    ++buttonEntries;
    buttonArgument = control;
    if (object != expected) ++failures;
    return originalButton(object, control);
}

// Synthetic mov imm32 + call prefix only; the helper is not an SEH frame.
static DWORD helperValue;
static int helperCalls;
static int prefixEntries;
__declspec(naked) void __cdecl PrefixHelper() {
    __asm {
        mov helperValue, eax
        inc helperCalls
        ret
    }
}
__declspec(naked) int __cdecl TestPrefix() {
    __asm {
        mov eax, 012345678h
        call PrefixHelper
        mov eax, [ecx]
        ret
    }
}
static Target originalPrefix = reinterpret_cast<Target>(&TestPrefix);
__declspec(noinline) int __fastcall PrefixHook(TestObject* object, void*) {
    ++prefixEntries;
    if (object != expected) ++failures;
    return originalPrefix(object);
}

// Save the caller's nonvolatile registers, seed them, and call through the
// original entry. The callee and hook must preserve EBX/ESI/EDI/EBP and ESP.
__declspec(naked) unsigned int __cdecl Probe(Target, TestObject*) {
    __asm {
        push ebp
        push ebx
        push esi
        push edi
        mov savedStack, esp
        mov ebx, 012345678h
        mov esi, 023456789h
        mov edi, 03456789ah
        mov ebp, 0456789abh
        mov ecx, [esp + 24]
        call dword ptr [esp + 20]
        mov outerResult, eax
        xor edx, edx
        cmp esp, savedStack
        je stack_ok
        or edx, 1
    stack_ok:
        cmp ebx, 012345678h
        je ebx_ok
        or edx, 2
    ebx_ok:
        cmp esi, 023456789h
        je esi_ok
        or edx, 4
    esi_ok:
        cmp edi, 03456789ah
        je edi_ok
        or edx, 8
    edi_ok:
        cmp ebp, 0456789abh
        je ebp_ok
        or edx, 16
    ebp_ok:
        mov esp, savedStack
        mov eax, edx
        pop edi
        pop esi
        pop ebx
        pop ebp
        ret
    }
}

int main() {
    static_assert(sizeof(void*) == 4, "x86 required");
    TestObject object{40, 0};
    expected = &object;
    auto* prefixCode = static_cast<unsigned char*>(DetourCodeFromPointer(reinterpret_cast<PVOID>(&TestPrefix), nullptr));
    const unsigned char expectedPrefix[] = {0xb8, 0x78, 0x56, 0x34, 0x12, 0xe8};
    if (!prefixCode || std::memcmp(prefixCode, expectedPrefix, sizeof(expectedPrefix)) != 0) {
        std::puts("synthetic prefix bytes unexpected");
        return 4;
    }
    if (DetourTransactionBegin() != NO_ERROR || DetourUpdateThread(GetCurrentThread()) != NO_ERROR ||
        DetourAttach(reinterpret_cast<PVOID*>(&original), reinterpret_cast<PVOID>(Hook)) != NO_ERROR ||
        DetourAttach(reinterpret_cast<PVOID*>(&originalButton), reinterpret_cast<PVOID>(ButtonHook)) != NO_ERROR ||
        DetourAttach(reinterpret_cast<PVOID*>(&originalPrefix), reinterpret_cast<PVOID>(PrefixHook)) != NO_ERROR ||
        DetourTransactionCommit() != NO_ERROR) {
        std::puts("attach failed");
        return 1;
    }
    Target entry = reinterpret_cast<Target>(&TestTarget);
    const unsigned int registers = Probe(entry, &object);
    ButtonTarget button = reinterpret_cast<ButtonTarget>(&TestButton);
    DWORD buttonBefore, buttonAfter;
    __asm mov buttonBefore, esp
    const int buttonResult = button(&object, 2007);
    __asm mov buttonAfter, esp
    const int modalOuter = outerResult;
    const bool ok = registers == 0 && entries == 2 && object.calls == 2 && nestedResult == 41
                    && modalOuter == 42 && failures == 0 && buttonBefore == buttonAfter
                    && buttonEntries == 1 && buttonArgument == 2007 && buttonResult == 2047;
    auto* trampoline = reinterpret_cast<const unsigned char*>(originalPrefix);
    std::int32_t displacement = 0;
    std::memcpy(&displacement, trampoline + 6, sizeof(displacement));
    const auto jumpTarget = static_cast<std::uintptr_t>(reinterpret_cast<std::uintptr_t>(trampoline + 10) + displacement);
    const bool boundary = std::memcmp(trampoline, expectedPrefix, 5) == 0 && trampoline[5] == 0xe9
                          && jumpTarget == reinterpret_cast<std::uintptr_t>(prefixCode + 5);
    std::printf("prefix=%02x%02x%02x%02x%02x trampoline=%02x%02x%02x%02x%02x%02x jump_to_entry_plus_5=%d\n",
                expectedPrefix[0], expectedPrefix[1], expectedPrefix[2], expectedPrefix[3], expectedPrefix[4],
                trampoline[0], trampoline[1], trampoline[2], trampoline[3], trampoline[4], trampoline[5], boundary);
    Target prefixEntry = reinterpret_cast<Target>(&TestPrefix);
    const unsigned int prefixRegisters = Probe(prefixEntry, &object);
    const bool prefixOk = boundary && prefixRegisters == 0 && outerResult == 40 && helperValue == 0x12345678
                          && helperCalls == 1 && prefixEntries == 1 && failures == 0;
    if (DetourTransactionBegin() != NO_ERROR || DetourUpdateThread(GetCurrentThread()) != NO_ERROR ||
        DetourDetach(reinterpret_cast<PVOID*>(&original), reinterpret_cast<PVOID>(Hook)) != NO_ERROR ||
        DetourDetach(reinterpret_cast<PVOID*>(&originalButton), reinterpret_cast<PVOID>(ButtonHook)) != NO_ERROR ||
        DetourDetach(reinterpret_cast<PVOID*>(&originalPrefix), reinterpret_cast<PVOID>(PrefixHook)) != NO_ERROR ||
        DetourTransactionCommit() != NO_ERROR) {
        std::puts("detach failed");
        return 2;
    }
    const int after = entry(&object);
    const int buttonAfterDetach = button(&object, 7);
    const int prefixAfterDetach = prefixEntry(&object);
    const bool unhooked = after == 43 && entries == 2 && object.calls == 3
                          && buttonAfterDetach == 47 && buttonEntries == 1
                          && prefixAfterDetach == 40 && prefixEntries == 1 && helperCalls == 2;
    std::printf("register_errors=%u entries=%d calls=%d nested=%d outer=%d failures=%d "
                "button_entries=%d button_arg=%d button_result=%d button_stack_ok=%d unhooked=%d\n",
                registers, entries, object.calls, nestedResult, modalOuter, failures,
                buttonEntries, buttonArgument, buttonResult, buttonBefore == buttonAfter, unhooked);
    std::printf("prefix_register_errors=%u helper_value=%08lx helper_calls=%d prefix_entries=%d prefix_ok=%d\n",
                prefixRegisters, helperValue, helperCalls, prefixEntries, prefixOk);
    return ok && prefixOk && unhooked ? 0 : 3;
}
