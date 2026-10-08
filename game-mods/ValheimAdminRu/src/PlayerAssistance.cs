using System.Collections.Generic;

namespace ValheimAdminRu
{
    public static class PlayerAssistance
    {
        private static readonly HashSet<int> Negative = new HashSet<int>
        {
            "Poison".GetStableHashCode(), "Burning".GetStableHashCode(), "Spirit".GetStableHashCode(),
            "Frost".GetStableHashCode(), "Lightning".GetStableHashCode(), "Smoked".GetStableHashCode(),
            "Tared".GetStableHashCode(), "Wet".GetStableHashCode(), "Cold".GetStableHashCode(),
            "Freezing".GetStableHashCode(), "Encumbered".GetStableHashCode(), "Puke".GetStableHashCode(),
            "Harpooned".GetStableHashCode()
        };

        public static string Heal(Player player)
        {
            player.Heal(player.GetMaxHealth(), true);
            return "Здоровье восстановлено.";
        }

        public static string RestoreStamina(Player player)
        {
            player.AddStamina(player.GetMaxStamina());
            return "Выносливость восстановлена.";
        }

        public static string ClearNegativeEffects(Player player)
        {
            SEMan manager = player.GetSEMan();
            int removed = 0;
            foreach (StatusEffect effect in new List<StatusEffect>(manager.GetStatusEffects()))
            {
                if (effect && IsNegative(effect) && manager.RemoveStatusEffect(effect, true)) removed++;
            }
            return removed == 0 ? "Негативных эффектов для снятия нет."
                : "Снято негативных эффектов: " + removed + ". Положительные эффекты сохранены.";
        }

        private static bool IsNegative(StatusEffect effect)
        {
            // StatusEffect has no universal negative flag. Keep unknown modded effects,
            // guardian powers, rested, food and cooldowns; recognize vanilla hazards.
            return Negative.Contains(effect.NameHash()) || effect is SE_Poison || effect is SE_Burning
                || effect is SE_Frost || effect is SE_Smoke || effect is SE_Wet || effect is SE_Puke
                || effect is SE_Harpooned;
        }
    }
}
