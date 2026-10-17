using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using HearthLauncher.Engine;

namespace HearthLauncher.Tests;

public static class GameVersionTests
{
    internal enum ConstantForm { Shortest, Short, Full }
    internal enum Malformation { None, Getter, ConstructorSignature, ConstructorType, TargetField, MultipleAssignments, Branch, ComputedPatch, DuplicateGetter, NonstaticField,
        FieldType, AssemblyName, NamespacedVersion, DuplicateVersionType, DuplicateGameVersionType, EarlyReturn, EarlyThrow, EarlyJump }
    static int checks;

    static void Check(bool value, string name)
    {
        if (!value) throw new Exception("Game version regression: " + name);
        checks++; Console.WriteLine("PASS game version: " + name);
    }

    // A real managed PE, constructed as data. Neither these fixtures nor the
    // game's assemblies are loaded into the runtime or executed by the tests.
    internal static byte[] Assembly(int major, int minor, int patch, bool decoy = true,
        ConstantForm form = ConstantForm.Shortest, Malformation malformation = Malformation.None, bool throwingInitializer = false)
    {
        var metadata = new MetadataBuilder();
        metadata.AddModule(0, metadata.GetOrAddString("assembly_valheim.dll"),
            metadata.GetOrAddGuid(new Guid("ddab2398-a2de-4c14-a6ea-d4c7e2aa47dc")), default, default);
        metadata.AddAssembly(metadata.GetOrAddString(malformation == Malformation.AssemblyName ? "UnityEngine" : "assembly_valheim"),
            new Version(9, 9, 9, 9), default, default, (AssemblyFlags)0, (AssemblyHashAlgorithm)0);
        var runtime = metadata.AddAssemblyReference(metadata.GetOrAddString("System.Runtime"), new Version(10, 0, 0, 0), default, default, (AssemblyFlags)0, default);
        var valueType = metadata.AddTypeReference(runtime, metadata.GetOrAddString("System"), metadata.GetOrAddString("ValueType"));
        metadata.AddTypeDefinition(TypeAttributes.NotPublic, default, metadata.GetOrAddString("<Module>"), default,
            MetadataTokens.FieldDefinitionHandle(1), MetadataTokens.MethodDefinitionHandle(1));
        metadata.AddTypeDefinition(TypeAttributes.Public | TypeAttributes.Sealed | TypeAttributes.SequentialLayout, default, metadata.GetOrAddString("GameVersion"), valueType,
            MetadataTokens.FieldDefinitionHandle(1), MetadataTokens.MethodDefinitionHandle(1));
        metadata.AddTypeDefinition(TypeAttributes.Public | TypeAttributes.Abstract | TypeAttributes.Sealed,
            malformation == Malformation.NamespacedVersion ? metadata.GetOrAddString("Some.Library") : default, metadata.GetOrAddString("Version"), default,
            MetadataTokens.FieldDefinitionHandle(4), MetadataTokens.MethodDefinitionHandle(2));
        int foreignConstructor = malformation == Malformation.DuplicateGetter ? 5 : 4;
        metadata.AddTypeDefinition(TypeAttributes.Public | TypeAttributes.Sealed | TypeAttributes.SequentialLayout, default, metadata.GetOrAddString("ForeignVersion"), valueType,
            MetadataTokens.FieldDefinitionHandle(6), MetadataTokens.MethodDefinitionHandle(foreignConstructor));
        if (malformation is Malformation.DuplicateVersionType or Malformation.DuplicateGameVersionType)
            metadata.AddTypeDefinition(TypeAttributes.Public, default, metadata.GetOrAddString(malformation == Malformation.DuplicateVersionType ? "Version" : "GameVersion"), default,
                MetadataTokens.FieldDefinitionHandle(6), MetadataTokens.MethodDefinitionHandle(foreignConstructor + 2));
        var integerField = metadata.GetOrAddBlob(new byte[] { 0x06, 0x08 });
        foreach (string name in new[] { "major", "minor", "patch" })
            metadata.AddFieldDefinition(FieldAttributes.Public, metadata.GetOrAddString(name), integerField);
        // FIELD VALUETYPE TypeDef(GameVersion row 2), encoded as (2 << 2).
        var versionField = metadata.GetOrAddBlob(new byte[] { 0x06, 0x11, 0x08 });
        var attributes = FieldAttributes.Private | FieldAttributes.InitOnly;
        if (malformation != Malformation.NonstaticField) attributes |= FieldAttributes.Static;
        var currentField = metadata.AddFieldDefinition(attributes, metadata.GetOrAddString("<CurrentVersion>k__BackingField"),
            malformation == Malformation.FieldType ? integerField : versionField);
        var legacyField = metadata.AddFieldDefinition(FieldAttributes.Private | FieldAttributes.Static, metadata.GetOrAddString("LegacyVersion"), versionField);
        var bodies = new BlobBuilder();
        int Body(List<byte> code)
        {
            bodies.Align(4); int offset = bodies.Count;
            bodies.WriteUInt16(0x3003); bodies.WriteUInt16(8); bodies.WriteInt32(code.Count); bodies.WriteInt32(0);
            bodies.WriteBytes(code.ToArray()); return offset;
        }
        void Integer(List<byte> code, int value)
        {
            if (form == ConstantForm.Shortest && value is >= -1 and <= 8) code.Add((byte)(value == -1 ? 0x15 : 0x16 + value));
            else if (form != ConstantForm.Full && value is >= sbyte.MinValue and <= sbyte.MaxValue)
            { code.Add(0x1F); code.Add(unchecked((byte)(sbyte)value)); }
            else { code.Add(0x20); code.AddRange(BitConverter.GetBytes(value)); }
        }
        static void Token(List<byte> code, byte opcode, EntityHandle token)
        { code.Add(opcode); code.AddRange(BitConverter.GetBytes(MetadataTokens.GetToken(token))); }
        void Assignment(List<byte> code, int a, int b, int c, FieldDefinitionHandle field, MethodDefinitionHandle constructor, bool computed = false)
        {
            Integer(code, a); code.Add(0x00); Integer(code, b);
            if (computed) Token(code, 0x28, MetadataTokens.MethodDefinitionHandle(foreignConstructor + 1));
            else Integer(code, c);
            Token(code, 0x73, constructor); Token(code, 0x80, field);
        }
        var cctor = new List<byte>();
        if (decoy)
        {
            // Unrelated compatibility version and string must never win over
            // the field explicitly returned by Version.get_CurrentVersion.
            Assignment(cctor, 8, 7, 66, legacyField, MetadataTokens.MethodDefinitionHandle(1));
            cctor.Add(0x72); cctor.AddRange(BitConverter.GetBytes(MetadataTokens.GetToken(metadata.GetOrAddUserString("99.9.999")))); cctor.Add(0x26);
        }
        if (malformation == Malformation.Branch) cctor.AddRange(new byte[] { 0x2B, 0x00 });
        if (malformation == Malformation.EarlyReturn) cctor.Add(0x2A);
        if (malformation == Malformation.EarlyThrow) cctor.AddRange(new byte[] { 0x14, 0x7A });
        if (malformation == Malformation.EarlyJump) Token(cctor, 0x27, MetadataTokens.MethodDefinitionHandle(foreignConstructor + 1));
        var selectedConstructor = MetadataTokens.MethodDefinitionHandle(malformation == Malformation.ConstructorType ? foreignConstructor : 1);
        Assignment(cctor, major, minor, patch, malformation == Malformation.TargetField ? legacyField : currentField,
            selectedConstructor, malformation == Malformation.ComputedPatch);
        if (malformation == Malformation.MultipleAssignments)
            Assignment(cctor, major, minor, patch, currentField, MetadataTokens.MethodDefinitionHandle(1));
        if (throwingInitializer) cctor.AddRange(new byte[] { 0x14, 0x7A }); else cctor.Add(0x2A);
        var getter = new List<byte>();
        if (malformation == Malformation.Getter) getter.Add(0x14);
        else { getter.Add(0x00); Token(getter, 0x7E, currentField); }
        getter.Add(0x2A);
        // DEFAULT/HASTHIS, parameter count, return type, then I4 parameters.
        var constructorSignature = metadata.GetOrAddBlob(malformation == Malformation.ConstructorSignature
            ? new byte[] { 0x20, 0x03, 0x01, 0x0E, 0x0E, 0x0E }
            : new byte[] { 0x20, 0x03, 0x01, 0x08, 0x08, 0x08 });
        var getterSignature = metadata.GetOrAddBlob(new byte[] { 0x00, 0x00, 0x11, 0x08 });
        var staticVoid = metadata.GetOrAddBlob(new byte[] { 0x00, 0x00, 0x01 });
        const MethodAttributes constructorAttributes = MethodAttributes.Public | MethodAttributes.SpecialName | MethodAttributes.RTSpecialName;
        metadata.AddMethodDefinition(constructorAttributes, MethodImplAttributes.IL, metadata.GetOrAddString(".ctor"), constructorSignature,
            Body([0x2A]), MetadataTokens.ParameterHandle(1));
        var getterMethod = metadata.AddMethodDefinition(MethodAttributes.Public | MethodAttributes.Static | MethodAttributes.SpecialName,
            MethodImplAttributes.IL, metadata.GetOrAddString("get_CurrentVersion"), getterSignature, Body(getter), MetadataTokens.ParameterHandle(1));
        metadata.AddMethodDefinition(MethodAttributes.Private | MethodAttributes.Static | MethodAttributes.SpecialName | MethodAttributes.RTSpecialName,
            MethodImplAttributes.IL, metadata.GetOrAddString(".cctor"), staticVoid, Body(cctor), MetadataTokens.ParameterHandle(1));
        if (malformation == Malformation.DuplicateGetter)
            metadata.AddMethodDefinition(MethodAttributes.Public | MethodAttributes.Static | MethodAttributes.SpecialName,
                MethodImplAttributes.IL, metadata.GetOrAddString("get_CurrentVersion"), getterSignature, Body(getter), MetadataTokens.ParameterHandle(1));
        metadata.AddMethodDefinition(constructorAttributes, MethodImplAttributes.IL, metadata.GetOrAddString(".ctor"),
            metadata.GetOrAddBlob(new byte[] { 0x20, 0x03, 0x01, 0x08, 0x08, 0x08 }), Body([0x2A]), MetadataTokens.ParameterHandle(1));
        var computed = new List<byte>(); Integer(computed, patch); computed.Add(0x2A);
        metadata.AddMethodDefinition(MethodAttributes.Public | MethodAttributes.Static, MethodImplAttributes.IL, metadata.GetOrAddString("ComputedPatch"),
            metadata.GetOrAddBlob(new byte[] { 0x00, 0x00, 0x08 }), Body(computed), MetadataTokens.ParameterHandle(1));
        var property = metadata.AddProperty(PropertyAttributes.None, metadata.GetOrAddString("CurrentVersion"), metadata.GetOrAddBlob(new byte[] { 0x08, 0x00, 0x11, 0x08 }));
        metadata.AddPropertyMap(MetadataTokens.TypeDefinitionHandle(3), property);
        metadata.AddMethodSemantics(property, MethodSemanticsAttributes.Getter, getterMethod);
        var image = new ManagedPEBuilder(new PEHeaderBuilder(imageCharacteristics: Characteristics.ExecutableImage | Characteristics.Dll),
            new MetadataRootBuilder(metadata), bodies, flags: CorFlags.ILOnly);
        var output = new BlobBuilder(); image.Serialize(output); return output.ToArray();
    }

    public static Task RunAsync()
    {
        string root = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "HearthLauncher-GameVersionTests-" + Guid.NewGuid().ToString("N")));
        Directory.CreateDirectory(root);
        try
        {
            string game = Path.Combine(root, "Valheim"), managed = Path.Combine(game, "valheim_Data", "Managed");
            Directory.CreateDirectory(managed); File.WriteAllText(Path.Combine(game, "valheim.exe"), "fixture; never executed");
            string assembly = Path.Combine(managed, "assembly_valheim.dll");
            Check(GameVersionReader.Read(game) is null, "missing game assembly remains unknown without creating it");
            void Read(byte[] content, string? expected, string name)
            { File.WriteAllBytes(assembly, content); Check(GameVersionReader.Read(game) == expected, name); }
            Read(Assembly(1, 0, 20), "1.0.20", "current game version is followed through getter and backing field, ignoring assembly/string/compatibility decoys");
            Read(Assembly(1, 0, 17, decoy: false), "1.0.17", "older three-part game version uses the same stable contract");
            Read(Assembly(1, 0, 20, form: ConstantForm.Short), "1.0.20", "short signed integer constants are read");
            Read(Assembly(1234, 5678, 1000, form: ConstantForm.Full), "1234.5678.1000", "full four-byte integer constants are read");
            Read(Assembly(1, 0, 0), "1.0", "zero patch follows GameVersion.ToString two-part format");
            Read(Assembly(1, 0, -3), "1.0.rc3", "negative patch follows release-candidate format");
            Read(Assembly(0, 0, 0), null, "uninitialized default game version is not presented as known");
            Read(Assembly(1, 0, 20, throwingInitializer: true), "1.0.20", "a throwing static initializer is inspected as data without executing game code");
            foreach (var malformed in Enum.GetValues<Malformation>().Where(value => value != Malformation.None))
                Read(Assembly(1, 0, 20, malformation: malformed), null, "unsupported or ambiguous contract stays unknown: " + malformed);
            Read([0x4D, 0x5A, 0x00, 0x01], null, "damaged PE remains unknown");
            Read(System.Text.Encoding.UTF8.GetBytes("Unity 6000.0.1f1; Valheim 1.0.20; not a managed assembly"), null,
                "a version string in another format is never mistaken for game metadata");
            File.WriteAllBytes(assembly, Assembly(1, 0, 20));
            var stamp = File.GetLastWriteTimeUtc(assembly);
            Check(GameVersionReader.Read(game) == "1.0.20", "initial installed assembly version is available");
            File.WriteAllBytes(assembly, Assembly(1, 0, 21)); File.SetLastWriteTimeUtc(assembly, stamp);
            Check(GameVersionReader.Read(game) == "1.0.21", "replacing an equally sized assembly with the same timestamp invalidates no persistent cache");
            string before = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assembly)));
            string[] files = Directory.GetFiles(game, "*", SearchOption.AllDirectories).Order().ToArray();
            for (int repeat = 0; repeat < 2; repeat++) _ = GameVersionReader.Read(game);
            Check(before == Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assembly))) && stamp == File.GetLastWriteTimeUtc(assembly)
                && files.SequenceEqual(Directory.GetFiles(game, "*", SearchOption.AllDirectories).Order()),
                "reading game version leaves files, contents and modification times unchanged");
            using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
            try { _ = GameVersionReader.Read(game, cancelled.Token); throw new Exception("Cancellation was ignored"); }
            catch (OperationCanceledException) { Check(true, "cancellation propagates rather than returning a made-up version"); }
            if (OperatingSystem.IsWindows())
            {
                using var exclusive = new FileStream(assembly, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
                Check(GameVersionReader.Read(game) is null, "temporarily inaccessible assembly remains unknown");
            }
            else if (OperatingSystem.IsLinux())
            {
                var mode = File.GetUnixFileMode(assembly);
                try
                {
                    File.SetUnixFileMode(assembly, UnixFileMode.None);
                    if (Environment.UserName != "root") Check(GameVersionReader.Read(game) is null, "unreadable assembly remains unknown");
                }
                finally { File.SetUnixFileMode(assembly, mode); }
                string realAssembly = Path.Combine(root, "real-assembly.dll"); File.Move(assembly, realAssembly);
                File.CreateSymbolicLink(assembly, realAssembly);
                Check(GameVersionReader.Read(game) is null && File.Exists(realAssembly), "linked game assembly is not followed or modified");
            }
            Console.WriteLine($"Game version tests: {checks} checks passed; fixture PE metadata was never executed.");
        }
        finally { Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
