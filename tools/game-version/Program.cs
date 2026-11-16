using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Text.RegularExpressions;

// Печатает версию Valheim из установленной сборки, не загружая её в процесс.
// Источник значения: статический инициализатор типа Version в assembly_valheim.dll.
if (args.Length != 1)
{
    Console.Error.WriteLine("usage: game-version <путь к assembly_valheim.dll>");
    return 2;
}

string path = args[0];
if (!File.Exists(path))
{
    Console.Error.WriteLine($"Нет файла: {path}");
    return 3;
}

using var module = ModuleDefinition.ReadModule(path, new ReaderParameters { ReadSymbols = false });
var pattern = new Regex(@"^\d+\.\d+\.\d+$");
foreach (var type in module.Types.Where(t => string.IsNullOrEmpty(t.Namespace) && t.Name == "Version"))
{
    foreach (var method in type.Methods.Where(m => m.Name == ".cctor" && m.HasBody))
    {
        foreach (var instruction in method.Body.Instructions)
        {
            if (instruction.OpCode == OpCodes.Ldstr && instruction.Operand is string text && pattern.IsMatch(text))
            {
                Console.WriteLine(text);
                return 0;
            }
        }
    }
}

Console.Error.WriteLine("Не удалось найти версию игры в сборке");
return 4;
