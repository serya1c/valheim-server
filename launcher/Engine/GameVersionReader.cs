using System.Buffers.Binary;
using System.Globalization;
using System.Reflection;
using System.Reflection.Emit;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;

namespace HearthLauncher.Engine;

// Inspect the installed game's version declaration. Never load a game assembly
// into the launcher or execute its constructors (which depend on Unity).
public static class GameVersionReader
{
    static readonly Dictionary<short, OpCode> Codes = typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)
        .Where(field => field.FieldType == typeof(OpCode)).Select(field => (OpCode)field.GetValue(null)!)
        .ToDictionary(code => code.Value);
    readonly record struct Instruction(OpCode Code, int Operand);

    public static string? Read(string game, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        try
        {
            string path = Installer.SafePath(game, "valheim_Data/Managed/assembly_valheim.dll");
            var before = new FileInfo(path);
            if (!before.Exists || before.Length is < 1 or > 268435456) return null;
            long length = before.Length; DateTime modified = before.LastWriteTimeUtc;
            using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            using var pe = new PEReader(input);
            if (!pe.HasMetadata) return null;
            var metadata = pe.GetMetadataReader();
            if (!metadata.IsAssembly || !metadata.StringComparer.Equals(metadata.GetAssemblyDefinition().Name, "assembly_valheim")
                || metadata.TypeDefinitions.Count > 100000) return null;
            TypeDefinitionHandle version = default, valueType = default;
            foreach (var handle in metadata.TypeDefinitions)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var type = metadata.GetTypeDefinition(handle);
                if (!type.Namespace.IsNil || !type.GetDeclaringType().IsNil) continue;
                if (metadata.StringComparer.Equals(type.Name, "Version")) { if (!version.IsNil) return null; version = handle; }
                if (metadata.StringComparer.Equals(type.Name, "GameVersion")) { if (!valueType.IsNil) return null; valueType = handle; }
            }
            if (version.IsNil || valueType.IsNil) return null;
            MethodDefinitionHandle getter = default, initializer = default;
            foreach (var handle in metadata.GetTypeDefinition(version).GetMethods())
            {
                var method = metadata.GetMethodDefinition(handle);
                if (metadata.StringComparer.Equals(method.Name, "get_CurrentVersion")) { if (!getter.IsNil) return null; getter = handle; }
                if (metadata.StringComparer.Equals(method.Name, ".cctor")) { if (!initializer.IsNil) return null; initializer = handle; }
            }
            if (getter.IsNil || initializer.IsNil) return null;
            var getterCode = Instructions(pe, metadata.GetMethodDefinition(getter), cancellationToken);
            if (getterCode.Count != 2 || getterCode[0].Code != OpCodes.Ldsfld || getterCode[1].Code != OpCodes.Ret) return null;
            var fieldHandle = MetadataTokens.EntityHandle(getterCode[0].Operand);
            if (fieldHandle.Kind != HandleKind.FieldDefinition) return null;
            var field = metadata.GetFieldDefinition((FieldDefinitionHandle)fieldHandle);
            if (field.GetDeclaringType() != version || (field.Attributes & FieldAttributes.Static) == 0) return null;
            var signature = metadata.GetBlobReader(field.Signature);
            // FIELD, VALUETYPE, then a compressed TypeDefOrRef handle.
            if (signature.ReadByte() != 0x06 || signature.ReadByte() != 0x11 || signature.ReadTypeHandle() != valueType || signature.RemainingBytes != 0) return null;
            var code = Instructions(pe, metadata.GetMethodDefinition(initializer), cancellationToken);
            if (code.Any(i => i.Code.FlowControl is FlowControl.Branch or FlowControl.Cond_Branch)) return null;
            var writes = code.Select((instruction, index) => (instruction, index))
                .Where(i => i.instruction.Code == OpCodes.Stsfld && i.instruction.Operand == getterCode[0].Operand).ToArray();
            if (writes.Length != 1 || writes[0].index < 4) return null;
            int end = writes[0].index;
            if (code.Take(end).Any(i => i.Code.FlowControl is FlowControl.Return or FlowControl.Throw || i.Code == OpCodes.Jmp)) return null;
            if (code[end - 1].Code != OpCodes.Newobj) return null;
            var constructorHandle = MetadataTokens.EntityHandle(code[end - 1].Operand);
            if (constructorHandle.Kind != HandleKind.MethodDefinition) return null;
            var constructor = metadata.GetMethodDefinition((MethodDefinitionHandle)constructorHandle);
            if (constructor.GetDeclaringType() != valueType || !metadata.StringComparer.Equals(constructor.Name, ".ctor")
                || !metadata.GetBlobBytes(constructor.Signature).AsSpan().SequenceEqual(new byte[] { 0x20, 3, 1, 8, 8, 8 })) return null;
            int? major = Constant(code[end - 4]), minor = Constant(code[end - 3]), patch = Constant(code[end - 2]);
            if (major is null or < 0 || minor is null or < 0 || patch is null || major == 0 && minor == 0 && patch == 0) return null;
            // Match GameVersion.ToString, including release candidates and a zero patch.
            string result = major.Value.ToString(CultureInfo.InvariantCulture) + "." + minor.Value.ToString(CultureInfo.InvariantCulture);
            if (patch > 0) result += "." + patch.Value.ToString(CultureInfo.InvariantCulture);
            if (patch < 0) result += ".rc" + (-(long)patch.Value).ToString(CultureInfo.InvariantCulture);
            var after = new FileInfo(path);
            cancellationToken.ThrowIfCancellationRequested();
            return after.Exists && after.Length == length && after.LastWriteTimeUtc == modified && input.Length == length ? result : null;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or BadImageFormatException
            or ArgumentException or InvalidOperationException or OverflowException)
        { return null; } // Unknown metadata must not discard the server or mod inspection.
    }

    static int? Constant(Instruction instruction)
    {
        if (instruction.Code == OpCodes.Ldc_I4 || instruction.Code == OpCodes.Ldc_I4_S) return instruction.Operand;
        if (instruction.Code.Value >= OpCodes.Ldc_I4_M1.Value && instruction.Code.Value <= OpCodes.Ldc_I4_8.Value)
            return instruction.Code.Value - OpCodes.Ldc_I4_0.Value;
        return null;
    }

    static List<Instruction> Instructions(PEReader pe, MethodDefinition method, CancellationToken cancellationToken)
    {
        if (method.RelativeVirtualAddress == 0) throw new BadImageFormatException();
        var body = pe.GetMethodBody(method.RelativeVirtualAddress);
        var bytes = body.GetILContent();
        if (body.ExceptionRegions.Length > 0 || bytes.Length > 65536) throw new BadImageFormatException();
        var code = bytes.AsSpan(); var result = new List<Instruction>();
        for (int position = 0; position < code.Length;)
        {
            cancellationToken.ThrowIfCancellationRequested();
            short value = code[position++];
            if (value == 0xfe)
            {
                if (position == code.Length) throw new BadImageFormatException();
                value = unchecked((short)(0xfe00 | code[position++]));
            }
            if (!Codes.TryGetValue(value, out var opcode)) throw new BadImageFormatException();
            int size = opcode.OperandType switch
            {
                OperandType.InlineNone => 0,
                OperandType.ShortInlineI or OperandType.ShortInlineVar or OperandType.ShortInlineBrTarget => 1,
                OperandType.InlineVar => 2,
                OperandType.InlineI8 or OperandType.InlineR => 8,
                OperandType.InlineSwitch => throw new BadImageFormatException(),
                OperandType.InlineI or OperandType.InlineBrTarget or OperandType.InlineField or OperandType.InlineMethod
                    or OperandType.InlineSig or OperandType.InlineString or OperandType.InlineTok or OperandType.InlineType or OperandType.ShortInlineR => 4,
                _ => throw new BadImageFormatException()
            };
            if (size > code.Length - position) throw new BadImageFormatException();
            int operand = size == 4 ? BinaryPrimitives.ReadInt32LittleEndian(code.Slice(position, size))
                : size == 1 ? (sbyte)code[position] : 0;
            position += size;
            if (opcode != OpCodes.Nop) result.Add(new(opcode, operand));
        }
        return result;
    }
}
