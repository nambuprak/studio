
"use client";

import Link from 'next/link';
import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger, DialogClose } from '@/components/ui/dialog';
import { ArrowLeft, PlusCircle, Edit, Trash2, Edit3 } from 'lucide-react';

interface Repository {
  id: string;
  name: string;
}

interface AdditionalInfoItem {
  id: string;
  title: string;
  description: string;
}

function EditPageContent() {
  const searchParams = useSearchParams();
  const [selectedRepo, setSelectedRepo] = useState<string>('');
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [repoOverview, setRepoOverview] = useState<string>('');
  const [tapBap, setTapBap] = useState<string>('');
  const [fileTypes, setFileTypes] = useState<string>('');
  const [excludeFolders, setExcludeFolders] = useState<string>('');

  const [additionalInfoList, setAdditionalInfoList] = useState<AdditionalInfoItem[]>([]);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [currentInfoTitle, setCurrentInfoTitle] = useState<string>('');
  const [currentInfoDescription, setCurrentInfoDescription] = useState<string>('');
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    async function fetchRepositories() {
      try {
        // Fetch from the relative path, Next.js dev server will proxy this
        const response = await fetch('/api/repos');
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data: Repository[] = await response.json();
        setRepositories(data);

        const repoIdFromQuery = searchParams.get('repoId');
        if (repoIdFromQuery && data.find(repo => repo.id === repoIdFromQuery)) {
          setSelectedRepo(repoIdFromQuery);
          // In a real application, you would fetch and pre-fill all other form data for this repoId
          // For now, we are only pre-selecting the repository.
          // Example:
          // const selectedRepoData = await fetch(`/api/repo-details/${repoIdFromQuery}`); // Note: uses relative path
          // const repoDetails = await selectedRepoData.json();
          // setRepoOverview(repoDetails.overview);
          // setTapBap(repoDetails.tapBap);
          // setFileTypes(repoDetails.fileTypes.join(','));
          // setExcludeFolders(repoDetails.excludeFolders.join(','));
          // setAdditionalInfoList(repoDetails.additionalInfoList);
        } else if (repoIdFromQuery) {
            alert("The repository ID from the URL was not found in the available repositories.");
        }

      } catch (error) {
        console.error("Failed to fetch repositories for edit page:", error);
        setRepositories([]);
        let errorMessage = "Could not fetch repositories for the edit page. Ensure the backend API server is running and accessible via /api/repos.";
        if (error instanceof Error && error.message) {
          errorMessage += `\nDetails: ${error.message}`;
        }
        alert(errorMessage);
      }
    }
    fetchRepositories();
  }, [searchParams]);

  const openModalForAdd = () => {
    setEditingId(null);
    setCurrentInfoTitle('');
    setCurrentInfoDescription('');
    setIsModalOpen(true);
  };

  const openModalForEdit = (id: string) => {
    const itemToEdit = additionalInfoList.find(item => item.id === id);
    if (itemToEdit) {
      setEditingId(id);
      setCurrentInfoTitle(itemToEdit.title);
      setCurrentInfoDescription(itemToEdit.description);
      setIsModalOpen(true);
    }
  };

  const handleSaveAdditionalInfo = () => {
    if (!currentInfoTitle.trim()) {
      alert("Title cannot be empty."); // Simple validation
      return;
    }
    if (editingId) {
      setAdditionalInfoList(additionalInfoList.map(item =>
        item.id === editingId ? { ...item, title: currentInfoTitle, description: currentInfoDescription } : item
      ));
    } else {
      setAdditionalInfoList([...additionalInfoList, { id: crypto.randomUUID(), title: currentInfoTitle, description: currentInfoDescription }]);
    }
    setIsModalOpen(false);
    setCurrentInfoTitle('');
    setCurrentInfoDescription('');
    setEditingId(null);
  };

  const handleDeleteAdditionalInfo = (id: string) => {
    setAdditionalInfoList(additionalInfoList.filter(item => item.id !== id));
  };

  const handleUpdate = () => {
    if (!selectedRepo) {
      alert("Please select a repository before updating.");
      return;
    }
    // In a real app, you'd send this data to a backend (e.g., your Flask API) to update the existing tutor
    console.log("Updating self tutor with data:", {
      selectedRepo,
      repoOverview,
      tapBap,
      fileTypes,
      excludeFolders,
      additionalInfoList,
    });
    // Example: await fetch(`/api/repo/${selectedRepo}`, { method: 'PUT', body: JSON.stringify(data) });
    alert("Self Tutor update initiated (see console for data). This would call a PUT/POST to your Flask API via a relative /api path.");
  };

  const handleDeleteTutor = () => {
    if (!selectedRepo) {
      alert("Please select a repository to delete.");
      return;
    }
    if (confirm("Are you sure you want to delete this Self Tutor configuration? This action cannot be undone.")) {
        console.log("Deleting self tutor configuration for repo:", selectedRepo);
        // Example: await fetch(`/api/repo/${selectedRepo}`, { method: 'DELETE' });
        alert("Self Tutor configuration deletion initiated. This would call a DELETE to your Flask API via a relative /api path.");
        handleClearForm();
    }
  };

  const handleClearForm = () => {
    const repoIdFromQuery = searchParams.get('repoId');
    if (repoIdFromQuery && repositories.find(repo => repo.id === repoIdFromQuery)) {
         setSelectedRepo(repoIdFromQuery);
    } else {
        setSelectedRepo('');
    }
    setRepoOverview('');
    setTapBap('');
    setFileTypes('');
    setExcludeFolders('');
    setAdditionalInfoList([]);
    console.log("Form cleared/reset. Original data would be re-fetched or restored in a full app.");
  };

  return (
    <main className="min-h-screen bg-background flex flex-col items-center py-8 px-4 sm:px-6 md:px-8">
      <Card className="w-full max-w-3xl shadow-xl rounded-lg">
        <CardHeader>
          <CardTitle className="text-3xl font-bold text-primary flex items-center">
            <Edit3 className="mr-3 h-8 w-8" /> Edit Self Tutor
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="repo-select-edit" className="text-base font-semibold">Select Repository</Label>
            <Select value={selectedRepo} onValueChange={setSelectedRepo} disabled={repositories.length === 0}>
              <SelectTrigger id="repo-select-edit" className="w-full text-base py-2.5">
                <SelectValue placeholder="Choose a repository..." />
              </SelectTrigger>
              <SelectContent>
                {repositories.length > 0 ? (
                  repositories.map((repo) => (
                    <SelectItem key={repo.id} value={repo.id} className="text-base">
                      {repo.name}
                    </SelectItem>
                  ))
                ) : (
                  <SelectItem value="loading" disabled className="text-base">
                     { "Failed to load or no repositories. Is the API server running?"}
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>

          <h2 className="text-xl font-semibold text-foreground pt-2">Repository Overview</h2>
          <div className="space-y-2">
            <Label htmlFor="repo-overview" className="sr-only">Repository Overview</Label>
            <Textarea
              id="repo-overview"
              placeholder="Describe the repository, its purpose, key technologies, etc."
              value={repoOverview}
              onChange={(e) => setRepoOverview(e.target.value)}
              className="w-full min-h-[12rem] text-base"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="tap-bap" className="text-base font-semibold">TAP / BAP</Label>
            <Input
              id="tap-bap"
              value={tapBap}
              onChange={(e) => setTapBap(e.target.value)}
              placeholder="e.g., Technical Audience Profile / Business Audience Profile"
              className="text-base"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="file-types" className="text-base font-semibold">File Types (comma-separated)</Label>
            <Input
              id="file-types"
              value={fileTypes}
              onChange={(e) => setFileTypes(e.target.value)}
              placeholder="e.g., .ts, .tsx, .md, .py"
              className="text-base"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="exclude-folders" className="text-base font-semibold">Exclude Folders (comma-separated)</Label>
            <Input
              id="exclude-folders"
              value={excludeFolders}
              onChange={(e) => setExcludeFolders(e.target.value)}
              placeholder="e.g., node_modules, .git, dist"
              className="text-base"
            />
          </div>

          <div className="space-y-4 pt-4 border-t">
            <h3 className="text-lg font-semibold text-foreground">Additional Specific Details</h3>
            <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
              <DialogTrigger asChild>
                <Button variant="outline" onClick={openModalForAdd}>
                  <PlusCircle className="mr-2 h-5 w-5" /> Add Additional Info
                </Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-[500px]">
                <DialogHeader>
                  <DialogTitle>{editingId ? 'Edit' : 'Add'} Additional Info</DialogTitle>
                </DialogHeader>
                <div className="grid gap-4 py-4">
                  <div className="grid grid-cols-4 items-center gap-x-4 gap-y-2">
                    <Label htmlFor="info-title" className="text-right col-span-1">
                      Title
                    </Label>
                    <Input
                      id="info-title"
                      value={currentInfoTitle}
                      onChange={(e) => setCurrentInfoTitle(e.target.value)}
                      className="col-span-3"
                      placeholder="e.g., Authentication Flow"
                    />
                  </div>
                  <div className="grid grid-cols-4 items-start gap-x-4 gap-y-2">
                    <Label htmlFor="info-description" className="text-right col-span-1 pt-2">
                      Description
                    </Label>
                    <Textarea
                      id="info-description"
                      value={currentInfoDescription}
                      onChange={(e) => setCurrentInfoDescription(e.target.value)}
                      className="col-span-3 min-h-[100px]"
                      placeholder="Provide detailed information..."
                    />
                  </div>
                </div>
                <DialogFooter>
                  <DialogClose asChild>
                    <Button type="button" variant="outline">Cancel</Button>
                  </DialogClose>
                  <Button type="button" onClick={handleSaveAdditionalInfo}>{editingId ? 'Save Changes' : 'Add Info'}</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            {additionalInfoList.length > 0 && (
              <div className="space-y-2 mt-4">
                <h4 className="text-md font-medium text-muted-foreground">Added Information:</h4>
                <ul className="border rounded-md bg-card">
                  {additionalInfoList.map((info, index) => (
                    <li key={info.id} className={`flex justify-between items-center p-3 ${index < additionalInfoList.length - 1 ? 'border-b' : ''}`}>
                      <span className="font-medium text-card-foreground break-all pr-2">{info.title}</span>
                      <div className="flex-shrink-0 space-x-1">
                        <Button variant="ghost" size="icon" onClick={() => openModalForEdit(info.id)} className="h-8 w-8">
                          <Edit className="h-4 w-4" />
                          <span className="sr-only">Edit {info.title}</span>
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => handleDeleteAdditionalInfo(info.id)} className="h-8 w-8 text-destructive hover:text-destructive">
                          <Trash2 className="h-4 w-4" />
                           <span className="sr-only">Delete {info.title}</span>
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="flex flex-col sm:flex-row justify-end space-y-3 sm:space-y-0 sm:space-x-3 pt-6 border-t mt-6">
             <Link href="/" passHref legacyBehavior>
              <Button variant="outline" size="lg" className="w-full sm:w-auto">
                <ArrowLeft className="mr-2 h-5 w-5" /> Go Home
              </Button>
            </Link>
            <Button variant="outline" size="lg" onClick={handleClearForm} className="w-full sm:w-auto">
              Clear Form
            </Button>
             <Button variant="destructive" size="lg" onClick={handleDeleteTutor} className="w-full sm:w-auto">
              <Trash2 className="mr-2 h-5 w-5" /> Delete Tutor
            </Button>
            <Button size="lg" onClick={handleUpdate} className="w-full sm:w-auto" disabled={!selectedRepo}>
              Update
            </Button>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}

// It's good practice to wrap components that use useSearchParams in a Suspense boundary
export default function EditPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <EditPageContent />
    </Suspense>
  );
}
