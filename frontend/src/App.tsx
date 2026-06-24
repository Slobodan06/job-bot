import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Center, Loader } from "@mantine/core";

import { AuthProvider } from "./auth/AuthContext";
import { AppLayout } from "./components/AppLayout";
import {
  BuilderRoute,
  GuestRoute,
  OwnerRoute,
  ProtectedRoute,
  RedirectHome,
  TemplatePickerRoute,
} from "./components/ProtectedRoute";

const HomePage = lazy(() => import("./pages/HomePage"));
const AuthPage = lazy(() => import("./pages/AuthPage"));
const CheckEmailPage = lazy(() => import("./pages/CheckEmailPage"));
const VerifyEmailPage = lazy(() => import("./pages/VerifyEmailPage"));
const PendingAccessPage = lazy(() => import("./pages/PendingAccessPage"));
const ProfilePage = lazy(() => import("./pages/ProfilePage"));
const MembersPage = lazy(() => import("./pages/MembersPage"));
const TemplatesPage = lazy(() => import("./pages/TemplatesPage"));

function PageLoader() {
  return (
    <Center mih="40dvh">
      <Loader color="teal" />
    </Center>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<RedirectHome />} />
              <Route
                path="auth"
                element={
                  <GuestRoute>
                    <AuthPage />
                  </GuestRoute>
                }
              />
              <Route path="auth/check-email" element={<CheckEmailPage />} />
              <Route path="auth/verify" element={<VerifyEmailPage />} />
              <Route
                path="pending-access"
                element={
                  <ProtectedRoute>
                    <PendingAccessPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="templates"
                element={
                  <TemplatePickerRoute>
                    <TemplatesPage />
                  </TemplatePickerRoute>
                }
              />
              <Route
                path="builder"
                element={
                  <BuilderRoute>
                    <HomePage />
                  </BuilderRoute>
                }
              />
              <Route
                path="profile"
                element={
                  <ProtectedRoute>
                    <ProfilePage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="admin/members"
                element={
                  <OwnerRoute>
                    <MembersPage />
                  </OwnerRoute>
                }
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </AuthProvider>
    </BrowserRouter>
  );
}
