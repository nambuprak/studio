
"use client";

import Link from 'next/link';
import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger, DialogClose } from '@/components/ui/dialog';
import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ArrowLeft, PlusSquare, PlusCircle, Edit, Trash2, Loader2 } from 'lucide-react';

interface AdditionalInfoItem {
  id: string;
  title: string;
  description: string;
}

const generateClientId = () => 'id-' + Date.now().toString(36) + Math.random().toString(36).substring(2);

type InputType = 'folder' | 'url';

export default function CreatePage() {
  const [inputType, setInputType] = useState<InputType>('folder');
  const [sourceLocation, setSourceLocation] = useState<string>('');
  const [repoOverview, setRepoOverview] = useState<string>('');
  const [tapBap, setTapBap] = useState<string>('');
  const [fileTypes, setFileTypes] = useState<string>('.js, .ts, .html, .css, .py, .json');
  const [excludeFolders, setExcludeFolders] = useState<string>('node_modules, dist, .git');
  const [embedRepo, setEmbedRepo] = useState<boolean>(false);
  
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [additionalInfoList, setAdditionalInfoList] = useState<AdditionalInfoItem[]>([]);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [currentInfoTitle, setCurrentInfoTitle] = useState<string>('');
  const [currentInfoDescription, setCurrentInfoDescription] = useState<string>('');
  const [editingId, setEditingId] = useState<string | null>(null);

  // State for status modal and polling
  const [isStatusModalOpen, setIsStatusModalOpen] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [processingTutorId, setProcessingTutorId] = useState<string | null>(null);
  const [isProcessingComplete, setIsProcessingComplete] = useState<boolean>(false);
  const [pollingIntervalId, setPollingIntervalId] = useState<NodeJS.Timeout | null>(null);


  const handleSourceTypeChange = (value: string) => {
    setInputType(value as InputType);
    setSourceLocation(''); // Clear source location when type changes
  };

  const handleSourceLocationChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setSourceLocation(event.target.value);
  };

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
      alert("Title cannot be empty.");
      return;
    }
    if (editingId) {
      setAdditionalInfoList(additionalInfoList.map(item =>
        item.id === editingId ? { ...item, title: currentInfoTitle, description: currentInfoDescription } : item
      ));
    } else {
      setAdditionalInfoList([...additionalInfoList, { id: generateClientId(), title: currentInfoTitle, description: currentInfoDescription }]);
    }
    setIsModalOpen(false);
    setCurrentInfoTitle('');
    setCurrentInfoDescription('');
    setEditingId(null);
  };

  const handleDeleteAdditionalInfo = (id: string) => {
    setAdditionalInfoList(additionalInfoList.filter(item => item.id !== id));
  };
  
  const fetchStatus = async (tutorId: string) => {
    try {
      const response = await fetch(`/api/tutor-status/${tutorId}`);
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: "Failed to parse error from status endpoint." }));
        setStatusMessage(`Error fetching status: ${errorData.detail || response.statusText}`);
        setIsProcessingComplete(true); // Stop polling on error
        if (pollingIntervalId) clearInterval(pollingIntervalId);
        setPollingIntervalId(null);
        return;
      }
      const statusData = await response.json();
      setStatusMessage(statusData.message || 'Processing...');
      
      if (statusData.status === 'COMPLETED' || statusData.status === 'FAILED') {
        setIsProcessingComplete(true);
        if (pollingIntervalId) clearInterval(pollingIntervalId);
        setPollingIntervalId(null);
        setProcessingTutorId(null); // Clear processing ID
      }
    } catch (error: any) {
      setStatusMessage(`Error fetching status: ${error.message}`);
      setIsProcessingComplete(true);
      if (pollingIntervalId) clearInterval(pollingIntervalId);
      setPollingIntervalId(null);
    }
  };

  useEffect(() => {
    if (processingTutorId && isStatusModalOpen && !isProcessingComplete) {
      const intervalId = setInterval(() => {
        fetchStatus(processingTutorId);
      }, 3000);
      setPollingIntervalId(intervalId);
      return () => {
        clearInterval(intervalId);
        setPollingIntervalId(null);
      };
    } else if (pollingIntervalId && (isProcessingComplete || !isStatusModalOpen)) {
        clearInterval(pollingIntervalId);
        setPollingIntervalId(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processingTutorId, isStatusModalOpen, isProcessingComplete]);


  const handleGenerate = async () => {
    if (!sourceLocation.trim()) {
      alert(`Please enter the ${inputType === 'folder' ? 'folder path' : 'repository URL'}.`);
      return;
    }
    setIsLoading(true); // For the initial POST request

    if (inputType === 'url' && embedRepo) {
        alert("Processing a repository URL with embedding enabled can take some time. The server will process it in the background. A status modal will appear.");
    }
    
    const payload = {
      input_type: inputType,
      source_location: sourceLocation,
      repo_overview: repoOverview,
      tap_bap: tapBap,
      file_types: fileTypes,
      exclude_folders: excludeFolders,
      additional_info_list: additionalInfoList.map(({ id, ...rest }) => rest), 
      embed_repo: embedRepo,
    };

    try {
      const response = await fetch('/api/analyze-repo', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const result = await response.json();

      if (!response.ok) { // Catches 4xx, 5xx errors for the initial POST
        throw new Error(result.error || result.detail || `Server error: ${response.status}`);
      }

      // If embedding is requested, server returns 202 and we start polling
      if (embedRepo && response.status === 202 && result.tutor_id) {
        setProcessingTutorId(result.tutor_id);
        setStatusMessage(result.message || "Processing initiated...");
        setIsProcessingComplete(false);
        setIsStatusModalOpen(true);
        setIsLoading(false); // Initial request done, modal takes over
         // Form can be cleared or user can navigate away
        // handleClearForm(); 
      } else { // Synchronous completion (embedRepo is false or other cases)
        alert(`Self Tutor created successfully!\nProject Name: ${result.project_name}\nTutor ID: ${result.tutor_id}\nFiles processed: ${result.discovered_files_count !== undefined ? result.discovered_files_count : 'N/A (Embedding skipped)'}\nMessage: ${result.message}`);
        setIsLoading(false);
        // handleClearForm(); 
      }
    } catch (error: any) {
      console.error("Failed to generate Self Tutor:", error);
      alert(`Failed to generate Self Tutor: ${error.message}`);
      setIsLoading(false);
    }
  };
  
  const closeStatusModal = () => {
    setIsStatusModalOpen(false);
    if (pollingIntervalId) clearInterval(pollingIntervalId);
    setPollingIntervalId(null);
    setProcessingTutorId(null);
    setStatusMessage('');
    setIsProcessingComplete(false);
  };

  const handleClearForm = () => {
    setInputType('folder');
    setSourceLocation('');
    setRepoOverview('');
    setTapBap('');
    setFileTypes('.js, .ts, .html, .css, .py, .json');
    setExcludeFolders('node_modules, dist, .git');
    setEmbedRepo(false);
    setAdditionalInfoList([]);
    console.log("Form cleared.");
  };

  return (
    <main className="min-h-screen bg-background flex flex-col items-center py-8 px-4 sm:px-6 md:px-8">
      <Card className="w-full max-w-3xl shadow-xl rounded-lg">
        <CardHeader>
          <CardTitle className="text-3xl font-bold text-primary flex items-center">
            <PlusSquare className="mr-3 h-8 w-8" /> Create a Self Tutor
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label className="text-base font-semibold">Source Type</Label>
            <RadioGroup
              value={inputType}
              onValueChange={handleSourceTypeChange}
              className="flex space-x-4"
            >
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="folder" id="folder" />
                <Label htmlFor="folder">Folder Directory</Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="url" id="url" />
                <Label htmlFor="url">Repository URL</Label>
              </div>
            </RadioGroup>
          </div>
          
          <div className="space-y-2">
            <Label htmlFor="source-location-input" className="text-base font-semibold">
              {inputType === 'folder' ? 'Project Folder Path' : 'Repository URL'}
            </Label>
            <Input
              id="source-location-input"
              type="text"
              value={sourceLocation}
              onChange={handleSourceLocationChange}
              placeholder={inputType === 'folder' ? 'e.g., /path/to/your/local/project' : 'e.g., https://github.com/your-username/your-repo.git'}
              className="text-base py-3 h-14"
            />
            {sourceLocation && (
              <p className="text-sm text-muted-foreground mt-1">
                Entered {inputType === 'folder' ? 'path' : 'URL'}: <span className="font-medium text-foreground">{sourceLocation}</span>
              </p>
            )}
          </div>

          <h2 className="text-xl font-semibold text-foreground pt-2">Provide a Repo Overview</h2>
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
            <Label htmlFor="file-types" className="text-base font-semibold">File Types (comma-separated, e.g., .ts,.py)</Label>
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
                  <Button type="button" variant="outline" onClick={() => setIsModalOpen(false)}>Cancel</Button>
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

          <div className="items-center flex space-x-2 pt-4 border-t mt-4">
            <Checkbox id="embed-repo" checked={embedRepo} onCheckedChange={(checked) => setEmbedRepo(Boolean(checked))} />
            <Label htmlFor="embed-repo" className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
              Embed Repository/Folder Content (processes files server-side - can be slow for URLs)
            </Label>
          </div>

          <div className="flex flex-col sm:flex-row justify-end space-y-3 sm:space-y-0 sm:space-x-3 pt-6 border-t mt-2">
             <Link href="/" passHref legacyBehavior>
              <Button variant="outline" size="lg" className="w-full sm:w-auto" disabled={isLoading && !isStatusModalOpen}>
                <ArrowLeft className="mr-2 h-5 w-5" /> Go Home
              </Button>
            </Link>
            <Button variant="destructive" size="lg" onClick={handleClearForm} className="w-full sm:w-auto" disabled={isLoading && !isStatusModalOpen}>
              Clear Form
            </Button>
            <Button size="lg" onClick={handleGenerate} className="w-full sm:w-auto" disabled={isLoading && !isStatusModalOpen}>
              {(isLoading && !isStatusModalOpen) && <Loader2 className="mr-2 h-5 w-5 animate-spin" />}
              {(isLoading && !isStatusModalOpen) ? "Submitting..." : "Generate Self Tutor"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Status Modal */}
      <Dialog open={isStatusModalOpen} onOpenChange={(open) => { if (!open && isProcessingComplete) closeStatusModal(); else if (!open && !isProcessingComplete) alert("Processing is ongoing. Please wait or ensure the server is responsive.");}}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>Processing Self Tutor</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="flex items-center justify-center space-x-2">
              {!isProcessingComplete && <Loader2 className="h-5 w-5 animate-spin text-primary" />}
              <p className="text-sm text-muted-foreground">{statusMessage}</p>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={closeStatusModal} disabled={!isProcessingComplete}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
