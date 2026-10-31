import { useEffect, useRef, useState } from "react";
import { Select, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import {
  nativeCliApi,
  type NativeCliModelChoices,
} from "../../api/modules/nativeCli";

export interface NativeModelPickerProps {
  agentId: string;
  threadId?: string | null;
  value?: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
}

/** Draft-only selection; sending the next turn applies and persists the snapshot. */
export function NativeModelPicker({
  agentId,
  threadId,
  value,
  onChange,
  disabled,
}: NativeModelPickerProps) {
  const { t } = useTranslation();
  const [view, setView] = useState<NativeCliModelChoices | null>(null);
  const [failed, setFailed] = useState(false);
  const generation = useRef(0);
  useEffect(() => {
    const token = ++generation.current;
    setView(null);
    setFailed(false);
    void nativeCliApi.models(agentId, threadId).then(
      (next) => {
        if (generation.current === token) setView(next);
      },
      () => {
        if (generation.current === token) setFailed(true);
      },
    );
    return () => {
      generation.current++;
    };
  }, [agentId, threadId]);
  const modelLabel = (model: string) =>
    view?.models.find((item) => item.value === model)?.name ||
    model ||
    t("nativeCli.picker.cliDefault");
  const inheritedLabel = t("nativeCli.picker.inherit", {
    model: modelLabel(view?.effective_model_id ?? ""),
  });
  const choices = [
    { value: "inherit", label: inheritedLabel },
    { value: "default", label: t("nativeCli.picker.cliDefault") },
    ...(view?.models ?? []).map((item) => ({
      value: `model:${item.value}`,
      label: item.name,
    })),
  ];
  const selected =
    value == null ? "inherit" : value === "" ? "default" : `model:${value}`;
  if (value && !view?.models.some((item) => item.value === value)) {
    choices.push({ value: selected, label: value });
  }
  return (
    <Tooltip
      title={failed ? t("nativeCli.picker.failed") : t("nativeCli.picker.hint")}
    >
      <Select
        aria-label={t("nativeCli.picker.label")}
        size="small"
        variant="borderless"
        value={selected}
        loading={!view && !failed}
        disabled={disabled || !view}
        style={{ minWidth: 120, maxWidth: 260 }}
        options={choices}
        onChange={(next) =>
          onChange(
            next === "inherit" ? null : next === "default" ? "" : next.slice(6),
          )
        }
        popupMatchSelectWidth={false}
        notFoundContent={t("nativeCli.picker.probeFirst")}
      />
    </Tooltip>
  );
}
