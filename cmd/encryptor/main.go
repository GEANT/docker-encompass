package main

import (
	"crypto/tls"
	"errors"
	"flag"
	"fmt"
	"io"
	"math/rand"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

type config struct {
	serverHost string
	token      string
	node       string
	outputPath string
	port       int
	useSRV     bool
	insecure   bool
	scheme     string
	timeout    time.Duration
}

func usage(w io.Writer) {
	fmt.Fprintln(w, "Usage: encryptor -h <hostname> -t <token> [--node <fqdn>] [--srv | --port <port>]")
	fmt.Fprintln(w, "       encryptor -h <hostname> -t <token> --port <port> -o /etc/puppetlabs/puppet/csr_attributes.yaml")
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Options:")
	fmt.Fprintln(w, "  -h, --host        ENC hostname/IP (or SRV base domain when --srv is used)")
	fmt.Fprintln(w, "  -t, --token       CSR API token (X-CSR-API-KEY)")
	fmt.Fprintln(w, "  -n, --node        Node fqdn to query (defaults to local hostname)")
	fmt.Fprintln(w, "  -o, --output      Write YAML output to a file (example: /etc/puppetlabs/puppet/csr_attributes.yaml)")
	fmt.Fprintln(w, "      --srv         Resolve endpoint via SRV record _enc-node._tcp.<host>")
	fmt.Fprintln(w, "      --port        Static port (mandatory when --srv is not used)")
	fmt.Fprintln(w, "      --scheme      http or https (default: http)")
	fmt.Fprintln(w, "  -k, --insecure    Skip TLS certificate verification (HTTPS only)")
	fmt.Fprintln(w, "      --timeout     HTTP timeout in seconds (default: 10)")
	fmt.Fprintln(w, "      --help        Show this help")
}

func parseArgs(args []string) (config, error) {
	var cfg config
	fs := flag.NewFlagSet("encryptor", flag.ContinueOnError)
	fs.SetOutput(io.Discard)

	var hostShort string
	var hostLong string
	var tokenShort string
	var tokenLong string
	var nodeShort string
	var nodeLong string
	var outputShort string
	var outputLong string
	var timeoutSeconds int
	var showHelp bool

	fs.StringVar(&hostShort, "h", "", "ENC host")
	fs.StringVar(&hostLong, "host", "", "ENC host")
	fs.StringVar(&tokenShort, "t", "", "API token")
	fs.StringVar(&tokenLong, "token", "", "API token")
	fs.StringVar(&nodeShort, "n", "", "Node fqdn")
	fs.StringVar(&nodeLong, "node", "", "Node fqdn")
	fs.StringVar(&outputShort, "o", "", "Output file path")
	fs.StringVar(&outputLong, "output", "", "Output file path")
	fs.BoolVar(&cfg.useSRV, "srv", false, "Use SRV lookup")
	fs.BoolVar(&cfg.insecure, "k", false, "Skip TLS verification")
	fs.BoolVar(&cfg.insecure, "insecure", false, "Skip TLS verification")
	fs.IntVar(&cfg.port, "port", 0, "Static port")
	fs.StringVar(&cfg.scheme, "scheme", "http", "Scheme")
	fs.IntVar(&timeoutSeconds, "timeout", 10, "Timeout seconds")
	fs.BoolVar(&showHelp, "help", false, "Show help")

	if err := fs.Parse(args); err != nil {
		return cfg, err
	}
	if showHelp {
		return cfg, flag.ErrHelp
	}

	cfg.serverHost = firstNonEmpty(hostShort, hostLong)
	cfg.token = firstNonEmpty(tokenShort, tokenLong)
	cfg.node = firstNonEmpty(nodeShort, nodeLong)
	cfg.outputPath = firstNonEmpty(outputShort, outputLong)
	cfg.scheme = strings.ToLower(strings.TrimSpace(cfg.scheme))
	cfg.timeout = time.Duration(timeoutSeconds) * time.Second

	if cfg.serverHost == "" {
		return cfg, errors.New("-h/--host is required")
	}
	if cfg.token == "" {
		return cfg, errors.New("-t/--token is required")
	}
	if cfg.useSRV && cfg.port != 0 {
		return cfg, errors.New("--srv and --port are mutually exclusive")
	}
	if !cfg.useSRV {
		if cfg.port == 0 {
			return cfg, errors.New("--port is mandatory unless --srv is used")
		}
		if cfg.port < 1 || cfg.port > 65535 {
			return cfg, errors.New("--port must be between 1 and 65535")
		}
	}
	if cfg.scheme != "http" && cfg.scheme != "https" {
		return cfg, errors.New("--scheme must be http or https")
	}
	if timeoutSeconds < 1 {
		return cfg, errors.New("--timeout must be >= 1")
	}
	if cfg.node == "" {
		hostname, err := os.Hostname()
		if err != nil || strings.TrimSpace(hostname) == "" {
			return cfg, errors.New("--node is required when local hostname cannot be determined")
		}
		cfg.node = hostname
	}

	return cfg, nil
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if trimmed := strings.TrimSpace(value); trimmed != "" {
			return trimmed
		}
	}
	return ""
}

func resolveTarget(cfg config) (string, int, error) {
	if cfg.useSRV {
		_, records, err := net.LookupSRV("puppet8", "tcp", cfg.serverHost)
		if err != nil {
			return "", 0, fmt.Errorf("SRV lookup failed for _puppet8._tcp.%s: %w", cfg.serverHost, err)
		}
		if len(records) == 0 {
			return "", 0, fmt.Errorf("no SRV records found for _puppet8._tcp.%s", cfg.serverHost)
		}
		record := records[rand.Intn(len(records))]
		host := strings.TrimSuffix(record.Target, ".")
		return host, int(record.Port), nil
	}

	ips, err := net.LookupIP(cfg.serverHost)
	if err != nil || len(ips) == 0 {
		return cfg.serverHost, cfg.port, nil
	}
	picked := ips[rand.Intn(len(ips))]
	return picked.String(), cfg.port, nil
}

func buildRequestURL(cfg config, host string, port int) string {
	hostPort := net.JoinHostPort(host, strconv.Itoa(port))
	path := "/hosts/" + url.PathEscape(cfg.node) + "/csr_attributes"
	return cfg.scheme + "://" + hostPort + path
}

func run(cfg config) error {
	host, port, err := resolveTarget(cfg)
	if err != nil {
		return err
	}

	requestURL := buildRequestURL(cfg, host, port)
	request, err := http.NewRequest(http.MethodGet, requestURL, nil)
	if err != nil {
		return fmt.Errorf("failed to build request: %w", err)
	}
	request.Header.Set("X-CSR-API-KEY", cfg.token)

	transport := &http.Transport{}
	if cfg.insecure {
		transport.TLSClientConfig = &tls.Config{InsecureSkipVerify: true} //nolint:gosec
	}

	client := &http.Client{
		Timeout:   cfg.timeout,
		Transport: transport,
	}
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer response.Body.Close()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		return fmt.Errorf("failed to read response body: %w", err)
	}

	if response.StatusCode != http.StatusOK {
		msg := strings.TrimSpace(string(body))
		if msg == "" {
			msg = response.Status
		}
		return fmt.Errorf("server returned %s: %s", response.Status, msg)
	}

	if cfg.outputPath == "" || cfg.outputPath == "-" {
		_, err = os.Stdout.Write(body)
		if err != nil {
			return fmt.Errorf("failed to write output: %w", err)
		}
		return nil
	}

	if err := os.WriteFile(cfg.outputPath, body, 0o600); err != nil {
		return fmt.Errorf("failed to write output file %q: %w", cfg.outputPath, err)
	}
	return nil
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
