const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { PassThrough } = require("node:stream");
const { FrameDecoder, NativePet } = require("../native-pet.cjs");
function packet(type, body) {
  const header = Buffer.alloc(5);
  header.writeUInt32LE(body.length + 1);
  header[4] = type;
  return Buffer.concat([header, body]);
}
function frame() {
  const body = Buffer.alloc(8 + 8);
  body.writeUInt32LE(2);
  body.writeUInt32LE(1, 4);
  Buffer.from([22, 22, 24, 255, 200, 240, 40, 128]).copy(body, 8);
  return packet(1, body);
}
const ready = () =>
  packet(
    2,
    Buffer.from(
      JSON.stringify({ type: "ready", rawInput: true, keyboardHook: true }),
    ),
  );
test("native frame decoding survives every-byte fragmentation and concatenated events", () => {
  const frames = [],
    events = [];
  const parser = new FrameDecoder(
    (value) => frames.push(value),
    (value) => events.push(value),
  );
  const all = Buffer.concat([
    ready(),
    frame(),
    packet(2, Buffer.from('{"type":"stats","keyboardEvents":4}')),
    frame(),
  ]);
  for (const byte of all) parser.push(Buffer.from([byte]));
  assert.equal(frames.length, 2);
  assert.equal(events.length, 2);
  assert.equal(frames[0].width, 2);
  assert.equal(frames[0].height, 1);
  assert.deepEqual([...frames[0].rgba], [22, 22, 24, 255, 200, 240, 40, 128]);
  assert.equal(events[1].keyboardEvents, 4);
});
test("corrupt native lengths and image dimensions are rejected before presentation", () => {
  for (const size of [0, 1, 0xffffffff, 4194314]) {
    const bytes = Buffer.alloc(4);
    bytes.writeUInt32LE(size);
    assert.throws(() =>
      new FrameDecoder(
        () => {},
        () => {},
      ).push(bytes),
    );
  }
  const invalid = Buffer.alloc(8);
  invalid.writeUInt32LE(1025);
  invalid.writeUInt32LE(1, 4);
  assert.throws(() =>
    new FrameDecoder(
      () => {},
      () => {},
    ).push(packet(1, invalid)),
  );
  assert.throws(() =>
    new FrameDecoder(
      () => {},
      () => {},
    ).push(packet(1, Buffer.alloc(1))),
  );
  assert.throws(() =>
    new FrameDecoder(
      () => {},
      () => {},
    ).push(packet(7, Buffer.from("invalid"))),
  );
});
function child() {
  const value = new EventEmitter();
  value.stdout = new PassThrough();
  value.stderr = new PassThrough();
  value.stdin = new PassThrough();
  value.commands = [];
  value.stdin.on("data", (b) => value.commands.push(b.toString()));
  value.kill = () => value.emit("exit", 0);
  return value;
}
test("stopping and replacing a native renderer cannot deliver old account frames", async () => {
  const first = child(),
    second = child(),
    children = [first, second],
    frames = [];
  const pet = new NativePet("DoraKuroCat.exe", () => children.shift());
  pet.on("frame", (value) => frames.push(value));
  const opening = pet.start();
  first.stdout.write(ready());
  await opening;
  first.stdout.write(frame());
  assert.equal(frames.length, 1);
  pet.stop();
  first.stdout.write(frame());
  assert.equal(frames.length, 1);
  const replacement = pet.start();
  second.stdout.write(ready());
  await replacement;
  first.stdout.write(frame());
  assert.equal(frames.length, 1);
  second.stdout.write(frame());
  assert.equal(frames.length, 2);
  pet.stop();
  first.emit("exit", 0);
  second.emit("exit", 0);
});
test("cancelling native startup settles immediately without waiting for readiness", async () => {
  const process = child(),
    pet = new NativePet("DoraKuroCat.exe", () => process);
  const opening = pet.start();
  pet.stop();
  await assert.rejects(opening, /取消/);
  process.emit("exit", 0);
});
test("native control commands keep paths, user text and arbitrary motions out of stdin", async () => {
  const process = child(),
    pet = new NativePet("DoraKuroCat.exe", () => process);
  const opening = pet.start();
  process.stdout.write(ready());
  await opening;
  pet.place({ x: -300, y: 20, width: 198, height: 198 }, 1.25);
  pet.place({ x: -300, y: 20, width: 198, height: 198 }, 1.25);
  pet.pause(true);
  pet.drag(true, 4, -2);
  pet.motion("footEasterEgg", false);
  pet.hover(184, 126);
  assert.equal(
    process.commands.filter((s) => s.startsWith("frame ")).length,
    1,
  );
  assert.ok(process.commands.includes("frame -300 20 198 198 198 198 1.25\n"));
  assert.throws(() => pet.motion("../user-data", true));
  assert.throws(() => pet.state("user-message\nquit"));
  assert.throws(() => pet.place({ x: NaN, y: 0, width: 198, height: 198 }));
  pet.stop();
  process.emit("exit", 0);
});
