package main

import (
	"crypto/subtle"
	"crypto/tls"
	"crypto/x509"
	"encoding/asn1"
	"encoding/pem"
	"errors"
	"flag"
	"fmt"
	"io"
	"math/rand"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

const (
	defaultConfigPath = "/etc/puppetlabs/puppet/decryptor.yaml"
	defaultTokenPath  = "/etc/puppetlabs/puppet/csr_api_key"
)

var challengePasswordOID = asn1.ObjectIdentifier{1, 2, 840, 113549, 1, 9, 7}

type config struct {
	Server struct {
		Host               string `yaml:"host"`
		Port               int    `yaml:"port"`
		SRV                bool   `yaml:"srv"`
		Scheme             string `yaml:"scheme"`
		InsecureSkipVerify bool   `yaml:"insecure_skip_verify"`
	} `yaml:"server"`
	Auth struct {
		TokenFile string `yaml:"token_file"`
	} `yaml:"auth"`
	Network struct {
		TimeoutSeconds int `yaml:"timeout_seconds"`
	} `yaml:"network"`
}

type responsePayload struct {
	CustomAttributes struct {
		ChallengePassword string `yaml:"challengePassword"`
	} `yaml:"custom_attributes"`
}

func usage(w io.Writer) {
	fmt.Fprintln(w, "Usage: decryptor [--config /etc/puppetlabs/puppet/decryptor.yaml] <certname>")
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Reads CSR PEM from stdin, fetches expected challengePassword from enCompass/enCapsule,")
	fmt.Fprintln(w, "and exits 0 on match, non-zero on mismatch or errors.")
}

func main() {
	cfgPath := flag.String("config", defaultConfigPath, "Path to decryptor YAML config")
	showHelp := flag.Bool("help", false, "Show help")
	flag.Parse()

	if *showHelp {
		usage(os.Stdout)
		os.Exit(0)
	}

	if flag.NArg() != 1 {
		usage(os.Stderr)
		os.Exit(2)
	}
	certname := strings.TrimSpace(flag.Arg(0))
	if certname == "" {
		fmt.Fprintln(os.Stderr, "certname argument is required")
		os.Exit(2)
	}

	cfg, err := loadConfig(*cfgPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "config error: %v\n", err)
		os.Exit(1)
	}

	csrChallenge, err := extractCSRChallengePassword(os.Stdin)
	if err != nil {
		fmt.Fprintf(os.Stderr, "csr error: %v\n", err)
		os.Exit(1)
	}

	token, err := loadToken(cfg.Auth.TokenFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "token error: %v\n", err)
		os.Exit(1)
	}

	expectedChallenge, err := fetchExpectedChallenge(cfg, certname, token)
	if err != nil {
		fmt.Fprintf(os.Stderr, "fetch error: %v\n", err)
		os.Exit(1)
	}

	if subtle.ConstantTimeCompare([]byte(csrChallenge), []byte(expectedChallenge)) == 1 {
		os.Exit(0)
	}

	fmt.Fprintln(os.Stderr, "challengePassword mismatch")
	os.Exit(1)
}

func loadConfig(path string) (config, error) {
	var cfg config
	raw, err := os.ReadFile(path)
	if err != nil {
		return cfg, fmt.Errorf("failed to read %s: %w", path, err)
	}
	if err := yaml.Unmarshal(raw, &cfg); err != nil {
		return cfg, fmt.Errorf("failed to parse %s: %w", path, err)
	}

	cfg.Server.Host = strings.TrimSpace(cfg.Server.Host)
	cfg.Server.Scheme = strings.ToLower(strings.TrimSpace(cfg.Server.Scheme))
	cfg.Auth.TokenFile = strings.TrimSpace(cfg.Auth.TokenFile)

	if cfg.Server.Host == "" {
		return cfg, errors.New("server.host is required")
	}
	if cfg.Server.Scheme == "" {
		cfg.Server.Scheme = "http"
	}
	if cfg.Server.Scheme != "http" && cfg.Server.Scheme != "https" {
		return cfg, errors.New("server.scheme must be http or https")
	}
	if cfg.Server.SRV {
		if cfg.Server.Port != 0 {
			return cfg, errors.New("server.port must be unset when server.srv is true")
		}
	} else {
		if cfg.Server.Port < 1 || cfg.Server.Port > 65535 {
			return cfg, errors.New("server.port must be set between 1 and 65535 when server.srv is false")
		}
	}
	if cfg.Auth.TokenFile == "" {
		cfg.Auth.TokenFile = defaultTokenPath
	}
	if !filepath.IsAbs(cfg.Auth.TokenFile) {
		return cfg, errors.New("auth.token_file must be an absolute path")
	}
	if cfg.Network.TimeoutSeconds <= 0 {
		cfg.Network.TimeoutSeconds = 5
	}

	return cfg, nil
}

func extractCSRChallengePassword(r io.Reader) (string, error) {
	raw, err := io.ReadAll(r)
	if err != nil {
		return "", fmt.Errorf("failed to read stdin: %w", err)
	}
	if len(strings.TrimSpace(string(raw))) == 0 {
		return "", errors.New("stdin CSR is empty")
	}

	der := raw
	if block, _ := pem.Decode(raw); block != nil {
		der = block.Bytes
	}

	csr, err := x509.ParseCertificateRequest(der)
	if err != nil {
		return "", fmt.Errorf("failed to parse CSR: %w", err)
	}
	if err := csr.CheckSignature(); err != nil {
		return "", fmt.Errorf("invalid CSR signature: %w", err)
	}

	for _, set := range csr.Attributes {
		if !set.Type.Equal(challengePasswordOID) {
			continue
		}
		for _, seq := range set.Value {
			for _, atv := range seq {
				if value := attributeValueToString(atv.Value); value != "" {
					return value, nil
				}
			}
		}
	}

	return "", errors.New("challengePassword attribute not found in CSR")
}

func attributeValueToString(value any) string {
	switch v := value.(type) {
	case string:
		return strings.TrimSpace(v)
	case []byte:
		return strings.TrimSpace(string(v))
	default:
		return strings.TrimSpace(fmt.Sprint(v))
	}
}

func loadToken(path string) (string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("failed to read token file %s: %w", path, err)
	}
	token := strings.TrimSpace(string(raw))
	if token == "" {
		return "", errors.New("token file is empty")
	}
	return token, nil
}

func fetchExpectedChallenge(cfg config, certname, token string) (string, error) {
	host, port, err := resolveTarget(cfg)
	if err != nil {
		return "", err
	}

	requestURL := buildRequestURL(cfg, host, port, certname)
	request, err := http.NewRequest(http.MethodGet, requestURL, nil)
	if err != nil {
		return "", fmt.Errorf("failed to build request: %w", err)
	}
	request.Header.Set("X-CSR-API-KEY", token)

	transport := &http.Transport{}
	if cfg.Server.InsecureSkipVerify {
		transport.TLSClientConfig = &tls.Config{InsecureSkipVerify: true} //nolint:gosec
	}

	client := &http.Client{
		Timeout:   time.Duration(cfg.Network.TimeoutSeconds) * time.Second,
		Transport: transport,
	}

	response, err := client.Do(request)
	if err != nil {
		return "", fmt.Errorf("request failed: %w", err)
	}
	defer response.Body.Close()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read response body: %w", err)
	}

	if response.StatusCode != http.StatusOK {
		return "", fmt.Errorf("server returned %s: %s", response.Status, strings.TrimSpace(string(body)))
	}

	var payload responsePayload
	if err := yaml.Unmarshal(body, &payload); err != nil {
		return "", fmt.Errorf("failed to parse YAML response: %w", err)
	}

	challenge := strings.TrimSpace(payload.CustomAttributes.ChallengePassword)
	if challenge == "" {
		return "", errors.New("custom_attributes.challengePassword missing in response")
	}
	return challenge, nil
}

func resolveTarget(cfg config) (string, int, error) {
	if cfg.Server.SRV {
		_, records, err := net.LookupSRV("puppet8", "tcp", cfg.Server.Host)
		if err != nil {
			return "", 0, fmt.Errorf("SRV lookup failed for _puppet8._tcp.%s: %w", cfg.Server.Host, err)
		}
		if len(records) == 0 {
			return "", 0, fmt.Errorf("no SRV records found for _puppet8._tcp.%s", cfg.Server.Host)
		}
		record := records[rand.Intn(len(records))]
		return strings.TrimSuffix(record.Target, "."), int(record.Port), nil
	}

	ips, err := net.LookupIP(cfg.Server.Host)
	if err != nil || len(ips) == 0 {
		return cfg.Server.Host, cfg.Server.Port, nil
	}
	return ips[rand.Intn(len(ips))].String(), cfg.Server.Port, nil
}

func buildRequestURL(cfg config, host string, port int, certname string) string {
	hostPort := net.JoinHostPort(host, strconv.Itoa(port))
	path := "/hosts/" + url.PathEscape(certname) + "/csr_attributes"
	return cfg.Server.Scheme + "://" + hostPort + path
}
