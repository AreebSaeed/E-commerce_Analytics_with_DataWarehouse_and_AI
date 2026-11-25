import "../style/visual.less";
import powerbi from "powerbi-visuals-api";
import { FormattingSettingsService } from "powerbi-visuals-utils-formattingmodel";
import { valueFormatter } from "powerbi-visuals-utils-formattingutils";
import { VisualSettings } from "./settings";

import IVisual = powerbi.extensibility.visual.IVisual;
import VisualConstructorOptions = powerbi.extensibility.visual.VisualConstructorOptions;
import VisualUpdateOptions = powerbi.extensibility.visual.VisualUpdateOptions;
import ISelectionId = powerbi.visuals.ISelectionId;
import ISelectionManager = powerbi.extensibility.ISelectionManager;
import IVisualHost = powerbi.extensibility.visual.IVisualHost;
import VisualTooltipDataItem = powerbi.extensibility.VisualTooltipDataItem;

const compactNumber = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const wholeNumber = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const themes = ["teal", "blue", "amber", "coral"];
const headlineMetrics = [
    {
        role: "gmv", label: "Gross merchandise value", caption: "Eligible item value + freight",
        display: (value: number) => `R$ ${compactNumber.format(value / 1_000_000)}M`,
        tooltip: (value: number) => currency.format(value),
    },
    {
        role: "orders", label: "Orders", caption: "Eligible, distinct orders",
        display: (value: number) => wholeNumber.format(value),
        tooltip: (value: number) => wholeNumber.format(value),
    },
    {
        role: "aov", label: "Average order value", caption: "GMV ÷ eligible orders",
        display: (value: number) => `R$ ${wholeNumber.format(value)}`,
        tooltip: (value: number) => currency.format(value),
    },
    {
        role: "onTime", label: "On-time delivery", caption: "Of delivered orders",
        display: (value: number) => `${value.toFixed(1)}%`,
        tooltip: (value: number) => `${value.toFixed(2)}%`,
    },
];

type Card = {
    label: string;
    value: string;
    caption: string;
    theme: string;
    tooltip: VisualTooltipDataItem[];
    selectionId?: ISelectionId;
};

function cardText(className: string, value: string): HTMLSpanElement {
    const element = document.createElement("span");
    element.className = className;
    element.textContent = value;
    return element;
}

function numeric(value: powerbi.PrimitiveValue | null | undefined): number | undefined {
    return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export class Visual implements IVisual {
    private readonly host: IVisualHost;
    private readonly selectionManager: ISelectionManager;
    private readonly formattingService = new FormattingSettingsService();
    private readonly root = document.createElement("div");
    private readonly grid = document.createElement("div");
    private readonly status = document.createElement("div");
    private readonly deltaFormat: Intl.NumberFormat;
    private settings = new VisualSettings();
    private selectableCards: {
        element: HTMLButtonElement;
        identity: ISelectionId
    }[] = [];

    constructor(options?: VisualConstructorOptions) {
        if (!options) {
            throw new Error("Power BI visual host options are required.");
        }
        this.host = options.host;
        this.selectionManager = this.host.createSelectionManager();
        this.deltaFormat = new Intl.NumberFormat(this.host.locale, {
            style: "percent",
            maximumFractionDigits: 1,
            signDisplay: "exceptZero",
        });
        this.root.className = "olist-kpi-visual";
        this.grid.className = "kpi-grid";
        this.status.className = "kpi-status";
        this.status.setAttribute("role", "status");
        this.status.textContent = "Loading KPI cards…";
        this.root.append(this.grid, this.status);
        options.element.append(this.root);

        this.selectionManager.registerOnSelectCallback(() => this.applySelection());
        this.root.addEventListener("click", (event) => {
            if (this.host.hostCapabilities.allowInteractions && event.target instanceof Element &&
                !event.target.closest(".kpi-card")) {
                void this.selectionManager.clear().then(() => this.applySelection());
            }
        });
        this.root.addEventListener("contextmenu", (event) => this.showContextMenu(event));
    }

    public update(options: VisualUpdateOptions): void {
        this.host.eventService.renderingStarted(options);
        try {
            const dataView = options.dataViews?.[0];
            const updateData = dataView !== undefined || (options.type & powerbi.VisualUpdateType.Data) !== 0;
            if (updateData) {
                this.settings = dataView
                    ? this.formattingService.populateFormattingSettingsModel(VisualSettings, dataView)
                    : new VisualSettings();
            }
            this.settings.applyTo(this.root, this.host.colorPalette);
            this.root.style.width = `${options.viewport.width}px`;
            this.root.style.height = `${options.viewport.height}px`;
            this.root.classList.toggle("two-columns", options.viewport.width <= 900);
            this.root.classList.toggle("medium", options.viewport.width <= 1200);
            this.root.classList.toggle("compact", options.viewport.width <= 620);
            this.root.classList.toggle("single-column", options.viewport.width < 350);
            if (updateData) {
                this.render(dataView?.categorical);
            }
            this.host.eventService.renderingFinished(options);
        } catch (error) {
            this.host.eventService.renderingFailed(options, String(error));
            throw error;
        }
    }

    public getFormattingModel(): powerbi.visuals.FormattingModel {
        return this.formattingService.buildFormattingModel(this.settings);
    }

    public destroy(): void {
        this.hideTooltip();
        this.root.remove();
    }

    private render(categorical: powerbi.DataViewCategorical | undefined): void {
        const activeElement = this.root.ownerDocument.activeElement;
        const focused = this.selectableCards.find(({ element }) => element === activeElement)?.identity;
        this.hideTooltip();
        this.selectableCards = [];
        const category = categorical?.categories?.find((column) => column.source.roles?.category);
        const columns = categorical?.values ?? [];
        const cards = category ? this.categoryCards(category, columns) : this.headlineCards(columns);
        this.grid.replaceChildren(...cards.map((card) => this.renderCard(card)));
        const hasBindings = columns.some((column) =>
            column.source.roles?.value || headlineMetrics.some(({ role }) => column.source.roles?.[role]),
        );
        this.status.hidden = cards.length > 0;
        this.status.textContent = hasBindings ? "No KPI data for the current filters."
            : "Add headline measures, or add Category and Value.";
        this.applySelection();
        if (focused) {
            this.selectableCards.find(({ identity }) => identity.equals(focused))?.element.focus({ preventScroll: true });
        }
    }

    private headlineCards(columns: readonly powerbi.DataViewValueColumn[]): Card[] {
        return headlineMetrics.flatMap((metric, index) => {
            const column = columns.find((item) => item.source.roles?.[metric.role]);
            if (!column?.values.length) {
                return [];
            }
            const value = numeric(column.values[0]);
            return [{
                label: metric.label,
                value: value === undefined ? "—" : metric.display(value),
                caption: metric.caption,
                theme: themes[index],
                tooltip: [{ displayName: metric.label, value: value === undefined ? "(Blank)" : metric.tooltip(value) }],
            }];
        });
    }

    private categoryCards(category: powerbi.DataViewCategoryColumn, columns: readonly powerbi.DataViewValueColumn[]): Card[] {
        const primary = columns.find((column) => column.source.roles?.value);
        if (!primary) {
            return [];
        }
        const comparison = columns.find((column) => column.source.roles?.comparison);
        const formatter = (source: powerbi.DataViewMetadataColumn) =>
            valueFormatter.create({ format: source.format, cultureSelector: this.host.locale });
        const categoryFormat = formatter(category.source);
        const primaryFormat = formatter(primary.source);
        const comparisonFormat = comparison && formatter(comparison.source);

        return category.values.map((categoryValue, index) => {
            const label = categoryValue == null ? "(Blank)" : categoryFormat.format(categoryValue);
            const value = numeric(primary.values[index]);
            const baseline = numeric(comparison?.values[index]);
            const formattedValue = value === undefined ? "—" : primaryFormat.format(value);
            const tooltip = [
                { displayName: category.source.displayName, value: label },
                { displayName: primary.source.displayName, value: value === undefined ? "(Blank)" : formattedValue },
            ];
            let caption = primary.source.displayName;
            if (comparison && comparisonFormat) {
                tooltip.push({
                    displayName: comparison.source.displayName,
                    value: baseline === undefined ? "(Blank)" : comparisonFormat.format(baseline),
                });
                if (value !== undefined && baseline !== undefined && baseline !== 0) {
                    const change = (value - baseline) / Math.abs(baseline);
                    if (Number.isFinite(change)) {
                        const delta = this.deltaFormat.format(change);
                        caption = `${delta} vs ${comparison.source.displayName}`;
                        tooltip.push({ displayName: "Change", value: delta });
                    }
                }
            }
            return {
                label,
                value: formattedValue,
                caption,
                theme: themes[index % themes.length],
                tooltip,
                selectionId: category.identity?.[index]
                    ? this.host.createSelectionIdBuilder().withCategory(category, index).createSelectionId()
                    : undefined,
            };
        });
    }

    private renderCard(card: Card): HTMLElement {
        const identity = this.host.hostCapabilities.allowInteractions ? card.selectionId : undefined;
        const element = identity ? document.createElement("button") : document.createElement("article");
        element.className = `kpi-card ${card.theme}`;
        const label = cardText("kpi-label", card.label);
        const arrow = cardText("kpi-arrow", "↗");
        arrow.setAttribute("aria-hidden", "true");
        label.append(arrow);
        const accent = cardText("kpi-accent", "");
        accent.setAttribute("aria-hidden", "true");
        element.append(label, cardText("kpi-value", card.value), cardText("kpi-caption", card.caption), accent);

        if (identity && element instanceof HTMLButtonElement) {
            element.type = "button";
            this.selectableCards.push({ element, identity });
            element.addEventListener("click", (event) => {
                event.stopPropagation();
                const multiSelect = event.ctrlKey || event.metaKey;
                const selected = this.selectionManager.getSelectionIds() as ISelectionId[];
                const clear = !multiSelect && selected.length === 1 && identity.equals(selected[0]);
                const pending = clear ? this.selectionManager.clear() : this.selectionManager.select(identity, multiSelect);
                void pending.then(() => this.applySelection());
            });
        }
        element.addEventListener("pointerenter", (event) => this.showTooltip(card, event));
        element.addEventListener("pointermove", (event) => this.moveTooltip(card, event));
        element.addEventListener("pointerleave", () => this.hideTooltip());
        element.addEventListener("focus", () => {
            if (element.matches(":focus-visible")) {
                this.showTooltip(card, element.getBoundingClientRect());
            }
        });
        element.addEventListener("blur", () => this.hideTooltip());
        return element;
    }

    private applySelection(): void {
        const selected = this.selectionManager.getSelectionIds() as ISelectionId[];
        const isMatch = (identity: ISelectionId) => selected.some((item) => item.includes(identity));
        const hasVisibleSelection = this.selectableCards.some(({ identity }) => isMatch(identity));
        for (const { element, identity } of this.selectableCards) {
            const pressed = isMatch(identity);
            element.setAttribute("aria-pressed", String(pressed));
            element.classList.toggle("is-dimmed", hasVisibleSelection && !pressed);
        }
    }

    private showTooltip(card: Card, position: PointerEvent | DOMRect): void {
        const service = this.host.tooltipService;
        if (!service.enabled() || ("pointerType" in position && position.pointerType === "touch")) {
            return;
        }
        const coordinates = "clientX" in position
            ? [position.clientX, position.clientY]
            : [position.left + position.width / 2, position.bottom];
        service.show({
            coordinates,
            isTouchEvent: false,
            dataItems: card.tooltip,
            identities: card.selectionId ? [card.selectionId] : []
        });
    }

    private moveTooltip(card: Card, event: PointerEvent): void {
        const service = this.host.tooltipService;
        if (event.pointerType !== "touch" && service.enabled()) {
            service.move({
                coordinates: [event.clientX, event.clientY],
                isTouchEvent: false,
                dataItems: card.tooltip,
                identities: card.selectionId ? [card.selectionId] : [],
            });
        }
    }

    private hideTooltip(): void {
        if (this.host.tooltipService.enabled()) {
            this.host.tooltipService.hide({ immediately: true, isTouchEvent: false });
        }
    }

    private showContextMenu(event: MouseEvent): void {
        if (!this.host.hostCapabilities.allowInteractions) {
            return;
        }
        const target = event.target;
        const card = target instanceof Element ? target.closest("button.kpi-card") : null;
        const identity = this.selectableCards.find(({ element }) => element === card)?.identity;
        const bounds = card?.getBoundingClientRect();
        const keyboard = event.clientX === 0 && event.clientY === 0 && bounds;
        void this.selectionManager.showContextMenu(identity ?? {}, {
            x: keyboard ? bounds.left + bounds.width / 2 : event.clientX,
            y: keyboard ? bounds.bottom : event.clientY,
        });
        event.preventDefault();
    }
}
