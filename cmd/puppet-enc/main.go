package main

import (
	"crypto/rand"
	"encoding/binary"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

type config struct {
	node     string
	server   string
	user     string
	password string
	srv      bool
	rrdns    bool
	port     int
}

func usage(w io.Writer) {
	fmt.Fprintln(w, "Usage: puppet-enc --node <node> --server <hostname> [--srv | --rrdns --port <port> | --port <port>] [--user <username> --password <password>]")
	fmt.Fprintln(w, "       puppet-enc -h | --help")
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Options:")
	fmt.Fprintln(w, "  -n, --node      Node to query")
	fmt.Fprintln(w, "  -s, --server    Server hostname/IP to connect")
	fmt.Fprintln(w, "  -u, --user      Username (jointly required with --password)")
	fmt.Fprintln(w, "  -p, --password  Password (jointly required with --user)")
	fmt.Fprintln(w, "      --srv       Resolve endpoint via SRV record _puppet8._tcp.<server>")
	fmt.Fprintln(w, "      --rrdns     Resolve <server> to multiple A/AAAA records and try each with --port")
	fmt.Fprintln(w, "      --port      Static port (required for non-SRV mode)")
}

func parseArgs(args []string) (config, error) {
	var cfg config

	fs := flag.NewFlagSet("puppet-enc", flag.ContinueOnError)
	fs.SetOutput(io.Discard)

	var nodeShort, nodeLong string
	var serverShort, serverLong string
	var userShort, userLong string
	var passwordShort, passwordLong string
	var showHelp bool

	fs.StringVar(&nodeShort, "n", "", "Node to query")
	fs.StringVar(&nodeLong, "node", "", "Node to query")
	fs.StringVar(&serverShort, "s", "", "Server hostname/IP to connect")
	fs.StringVar(&serverLong, "server", "", "Server hostname/IP to connect")
	fs.StringVar(&userShort, "u", "", "Username")
	fs.StringVar(&userLong, "user", "", "Username")
	fs.StringVar(&passwordShort, "p", "", "Password")
	fs.StringVar(&passwordLong, "password", "", "Password")
	fs.BoolVar(&cfg.srv, "srv", false, "Resolve endpoint via SRV record _puppet8._tcp.<server>")
	fs.BoolVar(&cfg.rrdns, "rrdns", false, "Resolve <server> to multiple A/AAAA records and try each with --port")
	fs.IntVar(&cfg.port, "port", -1, "Static port")
	fs.BoolVar(&showHelp, "h", false, "Show help")
	fs.BoolVar(&showHelp, "help", false, "Show help")

	if err := fs.Parse(args); err != nil {
		return cfg, err
	}
	if showHelp {
		return cfg, flag.ErrHelp
	}

	cfg.node = firstNonEmpty(nodeShort, nodeLong)
	cfg.server = firstNonEmpty(serverShort, serverLong)
	cfg.user = firstNonEmpty(userShort, userLong)
	cfg.password = firstNonEmpty(passwordShort, passwordLong)

	if cfg.server == "" {
		return cfg, errors.New("--server option must be provided")
	}
	if cfg.node == "" {
		return cfg, errors.New("--node option must be provided")
	}
	if (cfg.user == "") != (cfg.password == "") {
		return cfg, errors.New("both --user and --password options must be provided together")
	}
	if cfg.srv && cfg.rrdns {
		return cfg, errors.New("--srv and --rrdns are mutually exclusive")
	}
	if cfg.srv && cfg.port != -1 {
		return cfg, errors.New("--srv and --port are mutually exclusive")
	}
	if !cfg.srv && cfg.port == -1 {
		return cfg, errors.New("--port is required unless --srv is used")
	}
	if cfg.port != -1 && (cfg.port < 0 || cfg.port > 65535) {
		return cfg, errors.New("--port must be in range 0-65535")
	}

	return cfg, nil
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if t := strings.TrimSpace(v); t != "" {
			return t
		}
	}
	return ""
}

// pickRandomIndex returns a cryptographically random index in [0, size).
func pickRandomIndex(size int) (int, error) {
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		return 0, err
	}
	return int(binary.LittleEndian.Uint64(b[:]) % uint64(size)), nil
}

// resolveFromSRV looks up a random SRV record for _puppet8._tcp.<server>.
// The lookup is performed on every call so that autoscaled Nomad targets are
// always discovered fresh.
func resolveFromSRV(server string) (string, int, error) {
	_, records, err := net.LookupSRV("puppet8", "tcp", server)
	if err != nil {
		return "", 0, fmt.Errorf("SRV lookup failed for _puppet8._tcp.%s: %w", server, err)
	}
	if len(records) == 0 {
		return "", 0, fmt.Errorf("no SRV records found for _puppet8._tcp.%s", server)
	}
	idx, err := pickRandomIndex(len(records))
	if err != nil {
		return "", 0, err
	}
	r := records[idx]
	return strings.TrimSuffix(r.Target, "."), int(r.Port), nil
}

// resolveTargets returns all A/AAAA addresses for server when --rrdns is set,
// or just the server name itself. The lookup is performed on every call so that
// autoscaled Nomad targets are always discovered fresh.
func resolveTargets(server string, useRRDNS bool) ([]string, error) {
	if !useRRDNS {
		return []string{server}, nil
	}
	ips, err := net.LookupIP(server)
	if err != nil {
		return nil, fmt.Errorf("A/AAAA lookup failed for %s: %w", server, err)
	}
	if len(ips) == 0 {
		return nil, fmt.Errorf("--rrdns enabled but no A/AAAA records found for %s", server)
	}
	targets := make([]string, 0, len(ips))
	for _, ip := range ips {
		if ip.To4() != nil {
			targets = append(targets, ip.String())
		} else {
			targets = append(targets, "["+ip.String()+"]")
		}
	}
	return targets, nil
}

func queryENC(client *http.Client, cfg config, target string, port int) (string, error) {
	url := fmt.Sprintf("http://%s:%d/hosts/%s", target, port, cfg.node)
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return "", fmt.Errorf("failed to build request: %w", err)
	}
	if cfg.user != "" {
		req.SetBasicAuth(cfg.user, cfg.password)
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read response body: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		msg := strings.TrimSpace(string(body))
		if msg == "" {
			msg = resp.Status
		}
		return "", fmt.Errorf("status %s: %s", resp.Status, msg)
	}
	return string(body), nil
}

func run(cfg config) error {
	host := cfg.server
	port := cfg.port

	if cfg.srv {
		h, p, err := resolveFromSRV(cfg.server)
		if err != nil {
			return err
		}
		host = h
		port = p
	}

	targets, err := resolveTargets(cfg.server, cfg.rrdns)
	if err != nil {
		return err
	}
	if !cfg.rrdns {
		// In plain or SRV mode use the (possibly SRV-resolved) host directly.
		targets = []string{host}
	}

	// A single transport is shared across all retry targets so that TCP
	// keep-alive connections are reused where possible.
	transport := &http.Transport{
		DialContext:           (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		MaxIdleConns:          100,
		MaxIdleConnsPerHost:   10,
		IdleConnTimeout:       90 * time.Second,
		ExpectContinueTimeout: 1 * time.Second,
	}
	defer transport.CloseIdleConnections()

	client := &http.Client{
		Timeout:   20 * time.Second,
		Transport: transport,
	}

	var lastErr error
	for _, target := range targets {
		output, reqErr := queryENC(client, cfg, target, port)
		if reqErr == nil {
			fmt.Print(output)
			return nil
		}
		lastErr = reqErr
	}

	return fmt.Errorf("failed to query ENC (%v)", lastErr)
}

func main() {
	cfg, err := parseArgs(os.Args[1:])
	if errors.Is(err, flag.ErrHelp) {
		usage(os.Stdout)
		os.Exit(0)
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n\n", err)
		usage(os.Stderr)
		os.Exit(2)
	}

	if err := run(cfg); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
