#!/usr/bin/env python3
"""Exercise Swift's real wire encoder/decoder against the Photon TypeScript store.

No .env, network, Photon account, or real messages are used. Pass --photon-dir if
the service repository is elsewhere. Requires Xcode CLI tools and npm dependencies.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SWIFT = r'''
import Foundation
@main struct ContractFixture {
    static func main() throws {
        if CommandLine.arguments.count > 1 {
            let response = try JSONDecoder().decode(PhotonInboxResponse.self,
                from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
            guard PhotonPolicy.validInbox(response, after: 0), response.messages.count == 3,
                  response.messages.map(\.kind) == ["summary", "feedback", "answer"] else {
                fatalError("Swift rejected the TypeScript response")
            }
            print("Swift decoded the real server inbox: PASS")
            return
        }
        let now = Int64(Date().timeIntervalSince1970 * 1_000)
        var start = PhotonRecord(id: "start-trip", kind: "start", sessionID: "trip", atMS: now)
        start.source = "video"; start.locale = "en"
        var alert = PhotonRecord(id: "alert-event", kind: "alert", sessionID: "trip", atMS: now)
        alert.eventID = "event"; alert.frameID = 42; alert.category = "obstacle"
        alert.direction = "center"; alert.text = "Caution front. Check your path."
        alert.evidence = ["direction_basis:cameraImage", "observations:3"]
        alert.observedAtMS = now; alert.speechStatus = "started"
        var end = PhotonRecord(id: "end-trip", kind: "end", sessionID: "trip", atMS: now)
        end.reason = "Recorded video finished"
        var feedback = PhotonRecord(id: "feedback-event", kind: "feedback", sessionID: "trip", atMS: now)
        feedback.eventID = "event"; feedback.note = "The detected object was a shadow."
        var query = PhotonRecord(id: "query-event", kind: "query", sessionID: "trip", atMS: now)
        query.question = "Why did you warn me?"
        FileHandle.standardOutput.write(try JSONEncoder().encode(["records": [start, alert, end, feedback, query]]))
    }
}
'''
NODE = r'''
import fs from 'node:fs';
import assert from 'node:assert/strict';
const {Store} = await import('./src/store.ts');
const [fixture, state, inbox] = process.argv.slice(1);
const records = JSON.parse(fs.readFileSync(fixture, 'utf8')).records;
const store = new Store(state);
assert.deepEqual(store.sync(records), {accepted:5, duplicates:0});
assert.deepEqual(store.sync(records), {accepted:0, duplicates:5});
const messages = store.messages(0);
assert.equal(messages.messages.filter(m => m.kind === 'summary').length, 1);
assert.match(messages.messages[0].text, /Recorded demo/);
assert.equal(store.feedbackExport()[0].alert.frame_id, 42);
assert.equal(store.feedbackExport()[0].status, 'unreviewed');
fs.writeFileSync(inbox, JSON.stringify(messages));
console.log('TypeScript accepted Swift records, deduped replay and linked feedback: PASS');
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--photon-dir', type=Path, required=True)
    args = parser.parse_args()
    service = args.photon_dir.resolve()
    if not (service / 'src/store.ts').is_file():
        parser.error('Photon src/store.ts was not found')
    with tempfile.TemporaryDirectory(prefix='sky-photon-contract-') as scratch:
        folder = Path(scratch)
        source = folder / 'fixture.swift'
        source.write_text(SWIFT)
        executable = folder / 'fixture'
        subprocess.run(['xcrun', 'swiftc', '-module-cache-path', str(folder / 'cache'),
                        '-parse-as-library', str(ROOT / 'ios/CaptureCore/Sources/CaptureCore/PhotonProtocol.swift'),
                        str(source), '-o', str(executable)], check=True)
        fixture = folder / 'records.json'
        fixture.write_bytes(subprocess.check_output([str(executable)]))
        assert len(json.loads(fixture.read_text())['records']) == 5
        inbox = folder / 'inbox.json'
        subprocess.run(['node', '--import', 'tsx', '--input-type=module', '-e', NODE,
                        str(fixture), str(folder / 'state.json'), str(inbox)], cwd=service, check=True)
        subprocess.run([str(executable), str(inbox)], check=True)


if __name__ == '__main__':
    main()
