/** Solar Linear by 480 Design, CC BY 4.0. See public/third-party-notices/solar-icons.html. */
import { forwardRef } from "react";
import type { LucideIcon, LucideProps } from "lucide-react";
import paths from "./data.json";
export type { LucideIcon } from "lucide-react";

function icon(name: keyof typeof paths): LucideIcon {
  const Component = forwardRef<SVGSVGElement, LucideProps>(
    (
      {
        size = 24,
        color = "currentColor",
        absoluteStrokeWidth: _absoluteStrokeWidth,
        children: _children,
        ...props
      },
      ref,
    ) => (
      <svg
        {...props}
        ref={ref}
        width={props.width ?? size}
        height={props.height ?? size}
        viewBox="0 0 24 24"
        fill="none"
        color={color}
        aria-hidden={props["aria-label"] ? undefined : true}
        data-octop-icon={name}
        dangerouslySetInnerHTML={{ __html: paths[name] }}
      />
    ),
  );
  Component.displayName = `Arc${name}`;
  return Component;
}

export const Monitor = icon("Monitor");
export const MessageSquareText = icon("MessageSquareText");
export const Timer = icon("Timer");
export const SlidersHorizontal = icon("SlidersHorizontal");
export const Waypoints = icon("Waypoints");
export const Link2 = icon("Link2");
export const Database = icon("Database");
export const Cpu = icon("Cpu");
export const Library = icon("Library");
export const Users = icon("Users");
export const Activity = icon("Activity");
export const Share2 = icon("Share2");
export const Cloudy = icon("Cloudy");
export const Sparkles = icon("Sparkles");
export const Puzzle = icon("Puzzle");
export const Package = icon("Package");
export const HardDrive = icon("HardDrive");
export const GraduationCap = icon("GraduationCap");
export const Shield = icon("Shield");
export const PanelsTopLeft = icon("PanelsTopLeft");
export const Send = icon("Send");
export const Square = icon("Square");
export const MessageSquarePlus = icon("MessageSquarePlus");
export const Paperclip = icon("Paperclip");
export const FileUp = icon("FileUp");
export const FolderUp = icon("FolderUp");
export const Zap = icon("Zap");
export const Wand2 = icon("Wand2");
export const Mic = icon("Mic");
export const CircleDot = icon("CircleDot");
export const Play = icon("Play");
export const Loader2 = icon("Loader2");
export const Brain = icon("Brain");
export const BookOpen = icon("BookOpen");
export const Bot = icon("Bot");
export const Plus = icon("Plus");
export const Check = icon("Check");
export const ChevronLeft = icon("ChevronLeft");
export const ChevronRight = icon("ChevronRight");
export const ChevronDown = icon("ChevronDown");
export const Route = icon("Route");
export const Info = icon("Info");
export const Search = icon("Search");
export const ArrowRightLeft = icon("ArrowRightLeft");
export const ArrowLeftRight = icon("ArrowLeftRight");
export const X = icon("X");
export const Hammer = icon("Hammer");
export const ListTodo = icon("ListTodo");
export const MessageCircleQuestion = icon("MessageCircleQuestion");
export const ShieldAlert = icon("ShieldAlert");
export const ShieldCheck = icon("ShieldCheck");
export const ClipboardCheck = icon("ClipboardCheck");
export const Archive = icon("Archive");
export const ArrowDownToLine = icon("ArrowDownToLine");
export const ArrowUpToLine = icon("ArrowUpToLine");
export const BarChart3 = icon("BarChart3");
export const Braces = icon("Braces");
export const CircleHelp = icon("CircleHelp");
export const Clock = icon("Clock");
export const Cloud = icon("Cloud");
export const CloudRain = icon("CloudRain");
export const Code2 = icon("Code2");
export const Coins = icon("Coins");
export const Copy = icon("Copy");
export const CornerDownLeft = icon("CornerDownLeft");
export const Download = icon("Download");
export const ExternalLink = icon("ExternalLink");
export const Eye = icon("Eye");
export const EyeOff = icon("EyeOff");
export const FileArchive = icon("FileArchive");
export const FileAudio = icon("FileAudio");
export const FileCode = icon("FileCode");
export const FileImage = icon("FileImage");
export const FileJson = icon("FileJson");
export const FilePen = icon("FilePen");
export const FileSpreadsheet = icon("FileSpreadsheet");
export const FileText = icon("FileText");
export const FileType = icon("FileType");
export const FileVideo = icon("FileVideo");
export const FileX = icon("FileX");
export const Fingerprint = icon("Fingerprint");
export const FolderOpen = icon("FolderOpen");
export const GitFork = icon("GitFork");
export const Globe = icon("Globe");
export const GripVertical = icon("GripVertical");
export const Heart = icon("Heart");
export const Image = icon("Image");
export const Import = icon("Import");
export const Key = icon("Key");
export const List = icon("List");
export const Menu = icon("Menu");
export const MessageSquare = icon("MessageSquare");
export const MoreHorizontal = icon("MoreHorizontal");
export const MoreVertical = icon("MoreVertical");
export const NotebookText = icon("NotebookText");
export const Palette = icon("Palette");
export const PanelLeftOpen = icon("PanelLeftOpen");
export const PanelRight = icon("PanelRight");
export const Pencil = icon("Pencil");
export const Pin = icon("Pin");
export const PinOff = icon("PinOff");
export const Plug = icon("Plug");
export const Presentation = icon("Presentation");
export const RefreshCw = icon("RefreshCw");
export const Rocket = icon("Rocket");
export const RotateCcw = icon("RotateCcw");
export const Save = icon("Save");
export const Scale = icon("Scale");
export const ScrollText = icon("ScrollText");
export const Settings = icon("Settings");
export const Settings2 = icon("Settings2");
export const SquareMinus = icon("SquareMinus");
export const SquarePlus = icon("SquarePlus");
export const Sun = icon("Sun");
export const Table = icon("Table");
export const Terminal = icon("Terminal");
export const Trash2 = icon("Trash2");
export const Type = icon("Type");
export const Undo2 = icon("Undo2");
export const User = icon("User");
export const Volume2 = icon("Volume2");
export const Wrench = icon("Wrench");
export const Smile = icon("Smile");
export const Quote = icon("Quote");
