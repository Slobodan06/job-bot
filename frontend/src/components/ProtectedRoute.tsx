import { Navigate, useLocation } from "react-router-dom";
import { Center, Loader } from "@mantine/core";

import { useAuth, getPostAuthPath } from "../auth/AuthContext";
import { userCanBuild, userHasTemplate } from "../auth/api";

export function GuestRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading, user } = useAuth();

  if (loading) {
    return (
      <Center mih="50dvh">
        <Loader color="teal" />
      </Center>
    );
  }

  if (isAuthenticated && user) {
    return <Navigate to={getPostAuthPath(user)} replace />;
  }

  return children;
}

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <Center mih="50dvh">
        <Loader color="teal" />
      </Center>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/auth" state={{ from: location.pathname }} replace />;
  }

  return children;
}

export function VerifiedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <Center mih="50dvh">
        <Loader color="teal" />
      </Center>
    );
  }

  if (!user) {
    return <Navigate to="/auth" replace />;
  }

  if (!user.email_verified) {
    return <Navigate to="/auth/check-email" state={{ email: user.email }} replace />;
  }

  return children;
}

export function TemplatePickerRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <Center mih="50dvh">
        <Loader color="teal" />
      </Center>
    );
  }

  if (!user) {
    return <Navigate to="/auth" replace />;
  }

  if (!user.email_verified) {
    return <Navigate to="/auth/check-email" state={{ email: user.email }} replace />;
  }

  if (!userCanBuild(user)) {
    return <Navigate to="/pending-access" replace />;
  }

  return children;
}

export function BuilderRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <Center mih="50dvh">
        <Loader color="teal" />
      </Center>
    );
  }

  if (!user) {
    return <Navigate to="/auth" replace />;
  }

  if (!user.email_verified) {
    return <Navigate to="/auth/check-email" state={{ email: user.email }} replace />;
  }

  if (!userCanBuild(user)) {
    return <Navigate to="/pending-access" replace />;
  }

  if (!userHasTemplate(user)) {
    return <Navigate to="/templates" replace />;
  }

  return children;
}

export function OwnerRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <Center mih="50dvh">
        <Loader color="teal" />
      </Center>
    );
  }

  if (!user) {
    return <Navigate to="/auth" replace />;
  }

  if (user.role !== "owner") {
    return <Navigate to={userCanBuild(user) ? (userHasTemplate(user) ? "/builder" : "/templates") : "/pending-access"} replace />;
  }

  return children;
}

export function RedirectHome() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <Center mih="50dvh">
        <Loader color="teal" />
      </Center>
    );
  }

  return <Navigate to={getPostAuthPath(user)} replace />;
}
