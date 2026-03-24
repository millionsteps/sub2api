package admin

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/service"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func setupAccountDeleteByFileNameRouter() (*gin.Engine, *stubAdminService) {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	adminSvc := newStubAdminService()

	h := NewAccountHandler(
		adminSvc,
		nil,
		nil,
		nil,
		nil,
		nil,
		nil,
		nil,
		nil,
		nil,
		nil,
		nil,
		nil,
	)

	router.POST("/api/v1/admin/accounts/delete-by-file-names", h.DeleteByFileNames)
	return router, adminSvc
}

func TestDeleteByFileNamesDeletesMatchedAccounts(t *testing.T) {
	router, adminSvc := setupAccountDeleteByFileNameRouter()
	now := time.Now().UTC()
	adminSvc.accounts = []service.Account{
		{
			ID:        101,
			Name:      "codex-alice427dcd@pnj.sixthirtydance.org",
			Platform:  service.PlatformOpenAI,
			Type:      service.AccountTypeOAuth,
			Status:    service.StatusActive,
			CreatedAt: now,
			UpdatedAt: now,
		},
		{
			ID:        202,
			Name:      "antigravity-artemisultra662155@bngg.dsckck.com",
			Platform:  service.PlatformAntigravity,
			Type:      service.AccountTypeOAuth,
			Status:    service.StatusActive,
			CreatedAt: now,
			UpdatedAt: now,
		},
	}

	body, _ := json.Marshal(map[string]any{
		"file_names": []string{
			"alice427dcd@pnj.sixthirtydance.org.json",
			"antigravity-artemisultra662155@bngg.dsckck.com.json",
		},
	})
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/admin/accounts/delete-by-file-names",
		bytes.NewReader(body),
	)
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(rec, req)
	require.Equal(t, http.StatusOK, rec.Code)

	var resp map[string]any
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &resp))
	require.Equal(t, float64(0), resp["code"])

	data, ok := resp["data"].(map[string]any)
	require.True(t, ok)
	require.Equal(t, float64(2), data["requested_files"])
	require.Equal(t, float64(2), data["matched_files"])
	require.Equal(t, float64(2), data["deleted_accounts"])
	require.Equal(t, float64(0), data["not_found_files"])
	require.Equal(t, []int64{101, 202}, adminSvc.deletedAccountIDs)
}

func TestDeleteByFileNamesDryRunDoesNotDelete(t *testing.T) {
	router, adminSvc := setupAccountDeleteByFileNameRouter()
	now := time.Now().UTC()
	adminSvc.accounts = []service.Account{
		{
			ID:        101,
			Name:      "codex-alice427dcd@pnj.sixthirtydance.org",
			Platform:  service.PlatformOpenAI,
			Type:      service.AccountTypeOAuth,
			Status:    service.StatusActive,
			CreatedAt: now,
			UpdatedAt: now,
		},
	}

	body, _ := json.Marshal(map[string]any{
		"file_names": []string{"alice427dcd@pnj.sixthirtydance.org.json"},
		"dry_run":    true,
	})
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/admin/accounts/delete-by-file-names",
		bytes.NewReader(body),
	)
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(rec, req)
	require.Equal(t, http.StatusOK, rec.Code)
	require.Empty(t, adminSvc.deletedAccountIDs)
}

func TestDeleteByFileNamesReturnsNotFoundForUnsupportedName(t *testing.T) {
	router, adminSvc := setupAccountDeleteByFileNameRouter()
	adminSvc.accounts = nil

	body, _ := json.Marshal(map[string]any{
		"file_names": []string{"unsupported-bundle.json"},
	})
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/admin/accounts/delete-by-file-names",
		bytes.NewReader(body),
	)
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(rec, req)
	require.Equal(t, http.StatusOK, rec.Code)

	var resp map[string]any
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &resp))
	data, ok := resp["data"].(map[string]any)
	require.True(t, ok)
	require.Equal(t, float64(1), data["not_found_files"])
	require.Empty(t, adminSvc.deletedAccountIDs)
}
