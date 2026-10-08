using HarmonyLib;

namespace ValheimAdminRu
{
    [HarmonyPatch(typeof(ItemDrop.ItemData), "GetTooltip", new[]
    {
        typeof(ItemDrop.ItemData), typeof(int), typeof(bool), typeof(float), typeof(int), typeof(bool)
    })]
    internal static class ItemTooltipPatch
    {
        [HarmonyPriority(Priority.Last)]
        private static void Postfix(ref string __result)
        {
            if (Plugin.Instance == null || !Plugin.Instance.HideCheatedItemNote
                || string.IsNullOrEmpty(__result) || Localization.instance == null) return;

            // Remove only the native display line; item data and achievement checks
            // stay intact. The common static overload also handles existing items
            // and descriptions appended by another item.
            string note = "\n<color=#808080><i>"
                + Localization.instance.Localize("$achievements_cheated_item_inventory")
                + "</i></color>";
            __result = __result.Replace(note, "");
        }
    }
}
