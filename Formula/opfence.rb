# Homebrew formula for Opfence. This repository is its own tap:
#
#   brew tap sudheer215s/opfence https://github.com/sudheer215s/opfence
#   brew install --HEAD opfence
#
# Release tags add a url and sha256 (go run ./tools/brewformula -tag vX.Y.Z),
# after which a plain "brew install opfence" builds that release.
class Opfence < Formula
  desc "Decides which cloud API and MCP tool calls an AI coding agent may make"
  homepage "https://github.com/sudheer215s/opfence"
  license "Apache-2.0"
  head "https://github.com/sudheer215s/opfence.git", branch: "master"

  depends_on "go" => :build

  def install
    # The release builds' settings (.goreleaser.yaml): a static binary that
    # reports its version. std_go_args adds -trimpath and -s -w.
    ENV["CGO_ENABLED"] = "0"
    commit = build.head? ? Utils.git_short_head(length: 12) : ""
    ldflags = %W[
      -X github.com/rakeshnitb23/opfence/internal/version.Version=#{version}
      -X github.com/rakeshnitb23/opfence/internal/version.Commit=#{commit}
    ]
    system "go", "build", *std_go_args(ldflags:), "./cmd/opfence"
    generate_completions_from_executable(bin/"opfence", "completion")
  end

  def caveats
    <<~EOS
      Add Opfence's MCP hook to your agent's settings:
        opfence setup claude-code   (or cursor, gemini)
      Run an agent behind Opfence's proxy:
        opfence run -- claude
    EOS
  end

  test do
    assert_match "opfence #{version}", shell_output("#{bin}/opfence version")
    # The request that deleted a production database in April 2026 needs a
    # typed confirmation.
    (testpath/"delete.http").write <<~HTTP
      POST /graphql/v2 HTTP/1.1
      Host: backboard.railway.com
      Content-Type: application/json

      {"query":"mutation { volumeDelete(volumeId: \\"vol-123\\") }"}
    HTTP
    assert_match "CONFIRM", shell_output("#{bin}/opfence explain delete.http")
    system bin/"opfence", "catalog", "validate"
  end
end
