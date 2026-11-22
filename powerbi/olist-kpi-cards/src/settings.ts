import powerbi from "powerbi-visuals-api";
import { formattingSettings } from "powerbi-visuals-utils-formattingmodel";

class CardStyle extends formattingSettings.SimpleCard {
    name = "cardStyle";
    displayName = "Card style";

    background = new formattingSettings.ColorPicker({
        name: "background",
        displayName: "Background",
        value: { value: "#ffffff" },
    });
    valueColor = new formattingSettings.ColorPicker({
        name: "valueColor",
        displayName: "Value color",
        value: { value: "#243e47" },
    });
    accentColor = new formattingSettings.ColorPicker({
        name: "accentColor",
        displayName: "Primary accent",
        value: { value: "#27bcaa" },
    });
    valueSize = new formattingSettings.NumUpDown({
        name: "valueSize",
        displayName: "Value size (px)",
        value: 27,
        options: {
            minValue: { type: powerbi.visuals.ValidatorType.Min, value: 12 },
            maxValue: { type: powerbi.visuals.ValidatorType.Max, value: 60 },
        },
    });
    borderRadius = new formattingSettings.NumUpDown({
        name: "borderRadius",
        displayName: "Corner radius (px)",
        value: 14,
        options: {
            minValue: { type: powerbi.visuals.ValidatorType.Min, value: 0 },
            maxValue: { type: powerbi.visuals.ValidatorType.Max, value: 40 },
        },
    });
    slices = [this.background, this.valueColor, this.accentColor, this.valueSize, this.borderRadius];
}

export class VisualSettings extends formattingSettings.Model {
    cardStyle = new CardStyle();
    cards = [this.cardStyle];

    applyTo(element: HTMLElement, palette: powerbi.extensibility.ISandboxExtendedColorPalette): void {
        const style = this.cardStyle;
        element.style.setProperty("--card-background", style.background.value.value);
        element.style.setProperty("--value-color", style.valueColor.value.value);
        element.style.setProperty("--primary-color", style.accentColor.value.value);
        element.style.setProperty("--value-size", `${style.valueSize.value}px`);
        element.style.setProperty("--card-radius", `${style.borderRadius.value}px`);
        element.classList.toggle("high-contrast", palette.isHighContrast);
        if (palette.isHighContrast) {
            element.style.setProperty("--contrast-background", palette.background.value);
            element.style.setProperty("--contrast-foreground", palette.foreground.value);
            element.style.setProperty("--contrast-selection", palette.foregroundSelected.value);
        }
    }
}
