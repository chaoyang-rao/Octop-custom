export type AvatarMotion = "idle" | "think" | "work" | "wait" | "done";
export function avatarPose(
  motion: AvatarMotion,
  seconds: number,
): Readonly<Record<string, number>>;
export function createExpertAvatars(options: any): any;
export const SHAPES: readonly {
  id: string;
  name: string;
  mood: string;
  motion: string;
}[];
export const COLORS: readonly { id: string; name: string; hex: string }[];
export const VIEWBOXES: Readonly<Record<string, string>>;
export function avatarFrame(
  shape: string,
  color: string,
  seconds: number,
  pose?: ReturnType<typeof avatarPose>,
): {
  body: [number, number][];
  eyes: [number, number][][];
};
export function bubbleStyle(color: string): {
  backgroundColor: string;
  color: string;
};
export function animatedSvg(shape: string, color: string): string;
export function contrast(a: string, b: string): number;
